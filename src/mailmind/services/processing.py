"""邮件处理链：特征 → 垃圾判定 → 分类 → 自动回复决策（exp.md 2.3 的 ③–⑧）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mailmind.core.config import Settings
from mailmind.db.models import Account, Mail, MailVerdict, ReplyDraft
from mailmind.ml.classify import ClassificationDecision
from mailmind.ml.spam import SpamDecision
from mailmind.pipeline.features import FeatureBundle, SenderStats, build_features
from mailmind.pipeline.parse import ParsedMail
from mailmind.reply.generator import ReplyGenerator
from mailmind.reply.policy import ReplyContext
from mailmind.reply.sender import ReplySenderService
from mailmind.services import audit
from mailmind.services.runtime import Runtime


@dataclass
class ProcessingResult:
    mail_id: int
    spam: SpamDecision
    classification: ClassificationDecision
    reply_status: str = "none"  # none | pending_review | sent | rejected | failed
    draft_id: int | None = None
    policy_reason: str = "ok"

    def to_dict(self) -> dict:
        return {
            "mail_id": self.mail_id,
            "spam": self.spam.to_dict(),
            "classification": self.classification.to_dict(),
            "reply_status": self.reply_status,
            "draft_id": self.draft_id,
            "policy_reason": self.policy_reason,
        }


class ProcessingService:
    def __init__(self, settings: Settings, session: Session, runtime: Runtime) -> None:
        self.settings = settings
        self.session = session
        self.runtime = runtime
        self.policy = runtime.reply_policy()

    # ------------------------------------------------------------ 主流程
    def process(self, mail: Mail, parsed: ParsedMail, now: datetime | None = None) -> ProcessingResult:
        now = now or datetime.now(UTC)
        features = self.build_feature_bundle(mail, parsed)

        spam = self.runtime.spam_filter(self.session, mail.account_id).evaluate(features)
        classification = self.runtime.classifier(self.session, mail.account_id).classify(
            features, is_spam=spam.label != "ham"
        )

        self._save_verdict(mail, spam, classification)

        if spam.action == "quarantine":
            mail.status = "quarantined"
        else:
            mail.status = "classified"

        result = ProcessingResult(mail.id, spam, classification)

        ctx = self._reply_context(mail, parsed, spam, classification)
        policy_result = self.policy.check(ctx, now=now)
        result.policy_reason = policy_result.reason
        if not policy_result.allowed:
            result.reply_status = "skipped"
            self.session.flush()
            self._audit(mail, "mail.processed", {
                "spam_action": spam.action,
                "spam_score": spam.score,
                "category": classification.category,
                "reply": "skipped",
                "policy_reason": policy_result.reason,
            })
            return result

        result.reply_status, result.draft_id = self._handle_reply(mail, parsed, spam, classification)
        self.session.flush()
        self._audit(mail, "mail.processed", {
            "spam_action": spam.action,
            "spam_score": spam.score,
            "category": classification.category,
            "reply": result.reply_status,
            "draft_id": result.draft_id,
        })
        return result

    # ------------------------------------------------------------ 特征
    def build_feature_bundle(self, mail: Mail, parsed: ParsedMail) -> FeatureBundle:
        return build_features(parsed, self._sender_stats(mail))

    def _sender_stats(self, mail: Mail) -> SenderStats:
        total = self.session.scalar(
            select(func.count())
            .select_from(Mail)
            .where(Mail.account_id == mail.account_id, Mail.from_addr == mail.from_addr, Mail.id != mail.id)
        ) or 0
        spam = self.session.scalar(
            select(func.count())
            .select_from(Mail)
            .join(MailVerdict, MailVerdict.mail_id == Mail.id)
            .where(
                Mail.account_id == mail.account_id,
                Mail.from_addr == mail.from_addr,
                Mail.id != mail.id,
                MailVerdict.spam_label == "spam",
            )
        ) or 0
        first = self.session.scalar(
            select(func.min(Mail.received_at)).where(
                Mail.account_id == mail.account_id, Mail.from_addr == mail.from_addr
            )
        )
        return SenderStats(seen_count=int(total), spam_count=int(spam), first_seen=first)

    # ------------------------------------------------------------ 判定落库
    def _save_verdict(
        self, mail: Mail, spam: SpamDecision, classification: ClassificationDecision
    ) -> None:
        verdict = mail.verdict or MailVerdict(mail_id=mail.id)
        verdict.spam_score = spam.score
        verdict.spam_label = spam.label
        verdict.spam_action = spam.action
        verdict.spam_reasons = spam.reasons
        verdict.category = classification.category
        verdict.category_scores = classification.scores
        verdict.category_reason = classification.reason
        verdict.model_versions = {
            "spam": spam.model_version,
            "category": classification.model_version,
            "llm": getattr(self.runtime.llm, "name", ""),
        }
        verdict.decided_at = datetime.now(UTC)
        if mail.verdict is None:
            self.session.add(verdict)
            mail.verdict = verdict
        self.session.flush()

    # ------------------------------------------------------------ 自动回复
    def _reply_context(
        self,
        mail: Mail,
        parsed: ParsedMail,
        spam: SpamDecision,
        classification: ClassificationDecision,
    ) -> ReplyContext:
        return ReplyContext(
            account_id=mail.account_id,
            from_addr=mail.from_addr,
            subject=mail.subject,
            headers=dict(mail.headers or {}),
            references=list(parsed.references),
            in_reply_to=list(parsed.in_reply_to),
            category=classification.category,
            spam_label=spam.label,
            has_risky_attachment=parsed.has_risky_attachment,
            received_at=mail.received_at,
        )

    def _handle_reply(
        self,
        mail: Mail,
        parsed: ParsedMail,
        spam: SpamDecision,
        classification: ClassificationDecision,
    ) -> tuple[str, int | None]:
        generator = ReplyGenerator(
            self.settings, self.runtime.llm, self.runtime.retriever(self.session)
        )
        generation = generator.generate(
            subject=mail.subject, body=mail.text_body, session=self.session
        )

        draft = ReplyDraft(
            mail_id=mail.id,
            intent=generation.draft.intent,
            subject=generation.draft.subject,
            body=generation.draft.body,
            citations=generation.draft.citations,
            confidence=generation.confidence,
            status="rejected",
            model=generation.draft.model,
            risk_flags=generation.guardrail.risk_flags,
        )
        self.session.add(draft)
        self.session.flush()

        if generation.status == "rejected":
            mail.status = "classified"
            return "rejected", draft.id

        draft.status = "pending_review"
        if generation.status == "send" and self.settings.auto_reply_send_mode == "auto":
            outcome = self._send(mail, draft)
            return ("sent" if outcome.ok else "failed"), draft.id

        mail.status = "pending_review"
        return "pending_review", draft.id

    def _send(self, mail: Mail, draft: ReplyDraft):
        account = self.session.get(Account, mail.account_id)
        if account is None:  # pragma: no cover - 外键保证
            raise RuntimeError(f"账号不存在: {mail.account_id}")
        service = ReplySenderService(
            self.settings, self.session, self.runtime.sender_for(account), self.policy
        )
        return service.send_draft(draft, account=account, mail=mail)

    def _audit(self, mail: Mail, action: str, detail: dict) -> None:
        audit.record(
            self.session,
            actor="system:pipeline",
            action=action,
            target=f"mail:{mail.id}",
            detail=detail,
        )
