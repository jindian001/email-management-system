"""查询、反馈、隔离区与审核队列。"""

from __future__ import annotations

import base64
from datetime import UTC, datetime

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from mailmind.core.config import Settings
from mailmind.db.models import (
    Account,
    AuditLog,
    Feedback,
    Mail,
    MailVerdict,
    ReplyDraft,
    Rule,
)
from mailmind.reply.sender import ReplySenderService, SendOutcome
from mailmind.services import audit
from mailmind.services.runtime import Runtime


def _iso(value: datetime | None) -> str | None:
    """SQLite 读回的 datetime 不带时区，输出前统一补 UTC，避免前端解析歧义。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def encode_cursor(mail: dict) -> str:
    """游标 = base64(received_at|id)，避免深分页时 offset 扫描（exp.md 4.9）。"""
    raw = f"{mail.get('received_at') or ''}|{mail['id']}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int] | None:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded).decode()
        ts, mail_id = raw.rsplit("|", 1)
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is not None:  # 与 SQLite 存储的 naive UTC 对齐
            parsed = parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed, int(mail_id)
    except (ValueError, UnicodeDecodeError):
        return None


def serialize_mail(mail: Mail, *, detail: bool = False) -> dict:
    verdict = mail.verdict
    data: dict = {
        "id": mail.id,
        "account_id": mail.account_id,
        "message_id": mail.message_id,
        "thread_id": mail.thread_id,
        "folder": mail.folder,
        "from_addr": mail.from_addr,
        "from_name": mail.from_name,
        "to_addrs": mail.to_addrs,
        "subject": mail.subject,
        "received_at": _iso(mail.received_at),
        "sent_at": _iso(mail.sent_at),
        "status": mail.status,
        "has_attachment": mail.has_attachment,
        "snippet": (mail.text_body or "")[:200],
    }
    if verdict is not None:
        data["verdict"] = {
            "spam_label": verdict.spam_label,
            "spam_score": verdict.spam_score,
            "spam_action": verdict.spam_action,
            "spam_reasons": verdict.spam_reasons,
            "category": verdict.category,
            "category_scores": verdict.category_scores,
            "category_reason": verdict.category_reason,
            "model_versions": verdict.model_versions,
        }
    else:
        data["verdict"] = None
    if detail:
        data["text_body"] = mail.text_body
        data["headers"] = mail.headers
        data["attachments"] = [
            {
                "filename": a.filename,
                "content_type": a.content_type,
                "size_bytes": a.size_bytes,
                "sha256": a.sha256,
                "is_risky": a.is_risky,
            }
            for a in mail.attachments
        ]
        data["drafts"] = [serialize_draft(d) for d in mail.drafts]
    return data


def serialize_draft(draft: ReplyDraft) -> dict:
    return {
        "id": draft.id,
        "mail_id": draft.mail_id,
        "intent": draft.intent,
        "subject": draft.subject,
        "body": draft.body,
        "citations": draft.citations,
        "confidence": draft.confidence,
        "status": draft.status,
        "model": draft.model,
        "risk_flags": draft.risk_flags,
        "reviewer_id": draft.reviewer_id,
        "provider_message_id": draft.provider_message_id,
        "created_at": _iso(draft.created_at),
    }


class MailService:
    def __init__(self, settings: Settings, session: Session, runtime: Runtime) -> None:
        self.settings = settings
        self.session = session
        self.runtime = runtime

    # ------------------------------------------------------------ 查询
    def list_mails(
        self,
        *,
        account_id: int | None = None,
        status: str | None = None,
        category: str | None = None,
        spam_action: str | None = None,
        q: str | None = None,
        page: int = 1,
        size: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[dict], int]:
        stmt: Select = select(Mail)
        count_stmt = select(func.count()).select_from(Mail)
        if category or spam_action:
            stmt = stmt.join(MailVerdict, MailVerdict.mail_id == Mail.id)
            count_stmt = count_stmt.join(MailVerdict, MailVerdict.mail_id == Mail.id)
        if account_id is not None:
            stmt = stmt.where(Mail.account_id == account_id)
            count_stmt = count_stmt.where(Mail.account_id == account_id)
        if status:
            stmt = stmt.where(Mail.status == status)
            count_stmt = count_stmt.where(Mail.status == status)
        if category:
            stmt = stmt.where(MailVerdict.category == category)
            count_stmt = count_stmt.where(MailVerdict.category == category)
        if spam_action:
            stmt = stmt.where(MailVerdict.spam_action == spam_action)
            count_stmt = count_stmt.where(MailVerdict.spam_action == spam_action)
        if q:
            pattern = f"%{q}%"
            cond = or_(Mail.subject.ilike(pattern), Mail.text_body.ilike(pattern), Mail.from_addr.ilike(pattern))
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)

        total = int(self.session.scalar(count_stmt) or 0)
        if cursor:
            decoded = decode_cursor(cursor)
            if decoded is None:
                raise ValueError("cursor 非法")
            ts, last_id = decoded
            stmt = stmt.where(
                or_(
                    Mail.received_at < ts,
                    and_(Mail.received_at == ts, Mail.id < last_id),
                )
            )
        else:
            stmt = stmt.offset(max(page - 1, 0) * size)
        stmt = stmt.order_by(Mail.received_at.desc(), Mail.id.desc()).limit(size)
        rows = self.session.scalars(stmt).unique().all()
        return [serialize_mail(m) for m in rows], total

    def get_mail(self, mail_id: int) -> dict | None:
        mail = self.session.get(Mail, mail_id)
        return serialize_mail(mail, detail=True) if mail else None

    def raw_mail(self, mail_id: int) -> bytes | None:
        mail = self.session.get(Mail, mail_id)
        if mail is None or not mail.raw_object_key:
            return None
        return self.runtime.store.get(mail.raw_object_key)

    # ------------------------------------------------------------ 反馈
    def submit_feedback(
        self,
        mail_id: int,
        *,
        task: str,
        label: dict,
        note: str = "",
        source: str = "user",
    ) -> dict:
        mail = self.session.get(Mail, mail_id)
        if mail is None:
            raise LookupError(f"邮件不存在: {mail_id}")
        weight = 3.0 if source == "user" else 1.0
        feedback = Feedback(
            mail_id=mail_id, source=source, task=task, label=label, note=note, weight=weight
        )
        self.session.add(feedback)

        if task == "spam" and mail.verdict is not None:
            verdict = mail.verdict
            if label.get("label") == "ham":
                verdict.spam_label = "ham"
                verdict.spam_action = "pass"
                verdict.spam_score = 0.0
                if mail.status == "quarantined":
                    mail.status = "classified"
            elif label.get("label") == "spam":
                verdict.spam_label = "spam"
                verdict.spam_action = "quarantine"
                verdict.spam_score = max(verdict.spam_score, 0.99)
                mail.status = "quarantined"
        elif task == "category" and mail.verdict is not None:
            category = label.get("category")
            if category:
                mail.verdict.category = category

        audit.record(
            self.session,
            actor=f"{source}:feedback",
            action="mail.feedback",
            target=f"mail:{mail_id}",
            detail={"task": task, "label": label},
        )
        self.session.commit()
        return {"id": feedback.id, "mail_id": mail_id, "task": task, "label": label}

    # ------------------------------------------------------------ 隔离区
    def list_quarantine(self, page: int = 1, size: int = 50) -> tuple[list[dict], int]:
        return self.list_mails(status="quarantined", page=page, size=size)

    def release_quarantine(
        self, mail_id: int, *, add_allowlist: bool = True, actor: str = "user"
    ) -> dict:
        mail = self.session.get(Mail, mail_id)
        if mail is None:
            raise LookupError(f"邮件不存在: {mail_id}")
        if mail.verdict is not None:
            mail.verdict.spam_label = "ham"
            mail.verdict.spam_action = "pass"
            mail.verdict.spam_score = 0.0
        mail.status = "classified"
        rule = None
        if add_allowlist and mail.from_addr:
            domain = mail.from_addr.rsplit("@", 1)[-1]
            rule = Rule(
                scope="global",
                kind="allowlist",
                payload={"domains": [domain], "addresses": [mail.from_addr]},
                action="ham",
                priority=1,
                description=f"隔离区放行自动加入白名单: {mail.from_addr}",
                created_by=actor,
            )
            self.session.add(rule)
        audit.record(
            self.session,
            actor=actor,
            action="quarantine.released",
            target=f"mail:{mail_id}",
            detail={"allowlist_rule": rule.id if rule else None},
        )
        self.session.commit()
        return serialize_mail(mail, detail=True)

    def delete_quarantine(self, mail_id: int, *, actor: str = "user") -> bool:
        mail = self.session.get(Mail, mail_id)
        if mail is None:
            return False
        mail.status = "deleted"
        audit.record(self.session, actor=actor, action="quarantine.deleted", target=f"mail:{mail_id}")
        self.session.commit()
        return True

    # ------------------------------------------------------------ 草稿
    def list_drafts(self, status: str | None = None, page: int = 1, size: int = 50) -> list[dict]:
        stmt = select(ReplyDraft).order_by(ReplyDraft.created_at.desc(), ReplyDraft.id.desc())
        if status:
            stmt = stmt.where(ReplyDraft.status == status)
        stmt = stmt.offset(max(page - 1, 0) * size).limit(size)
        return [serialize_draft(d) for d in self.session.scalars(stmt).all()]

    def generate_draft(self, mail_id: int) -> dict:
        """按需为某一封邮件重新起草（exp.md 4.9 的 /reply/draft）。"""
        from mailmind.core.config import Settings  # noqa: F401 - 仅类型说明
        from mailmind.db.models import Mail as MailModel
        from mailmind.reply.generator import ReplyGenerator

        mail = self.session.get(MailModel, mail_id)
        if mail is None:
            raise LookupError(f"邮件不存在: {mail_id}")
        generator = ReplyGenerator(
            self.settings, self.runtime.llm, self.runtime.retriever(self.session)
        )
        result = generator.generate(subject=mail.subject, body=mail.text_body, session=self.session)
        draft = ReplyDraft(
            mail_id=mail.id,
            intent=result.draft.intent,
            subject=result.draft.subject,
            body=result.draft.body,
            citations=result.draft.citations,
            confidence=result.confidence,
            status="pending_review" if result.status in {"send", "pending_review"} else "rejected",
            model=result.draft.model,
            risk_flags=result.guardrail.risk_flags,
        )
        self.session.add(draft)
        if draft.status == "pending_review" and mail.status == "classified":
            mail.status = "pending_review"
        self.session.commit()
        return serialize_draft(draft)

    def approve_draft(
        self,
        draft_id: int,
        *,
        reviewer_id: str,
        body: str | None = None,
        actor: str = "reviewer",
    ) -> dict:
        draft = self.session.get(ReplyDraft, draft_id)
        if draft is None:
            raise LookupError(f"草稿不存在: {draft_id}")
        mail = self.session.get(Mail, draft.mail_id)
        account = self.session.get(Account, mail.account_id) if mail else None
        if mail is None or account is None:
            raise LookupError(f"草稿关联邮件/账号不存在: {draft_id}")

        service = ReplySenderService(
            self.settings, self.session, self.runtime.sender_for(account), self.runtime.reply_policy()
        )
        outcome: SendOutcome = service.approve_and_send(
            draft, account=account, mail=mail, reviewer_id=reviewer_id, body=body
        )
        audit.record(
            self.session,
            actor=actor,
            action="reply.approved",
            target=f"reply_draft:{draft_id}",
            detail={"ok": outcome.ok, "status": outcome.status, "error": outcome.error},
        )
        self.session.commit()
        return {
            "ok": outcome.ok,
            "status": outcome.status,
            "provider_message_id": outcome.provider_message_id,
            "error": outcome.error,
            "draft": serialize_draft(draft),
        }

    def reject_draft(self, draft_id: int, *, reviewer_id: str, reason: str = "") -> dict:
        draft = self.session.get(ReplyDraft, draft_id)
        if draft is None:
            raise LookupError(f"草稿不存在: {draft_id}")
        draft.status = "rejected"
        draft.reviewer_id = reviewer_id
        self.session.add(
            Feedback(
                mail_id=draft.mail_id,
                source="reviewer",
                task="reply_quality",
                label={"draft_id": draft_id, "accepted": False},
                note=reason,
                weight=2.0,
            )
        )
        mail = self.session.get(Mail, draft.mail_id)
        if mail is not None:
            mail.status = "classified"
        audit.record(
            self.session,
            actor=f"user:{reviewer_id}",
            action="reply.rejected",
            target=f"reply_draft:{draft_id}",
            detail={"reason": reason},
        )
        self.session.commit()
        return serialize_draft(draft)

    def send_latest_draft(
        self, mail_id: int, *, reviewer_id: str, body: str | None = None
    ) -> dict:
        """``POST /mails/{id}/reply/send``：把该邮件最新待审草稿审核并发送。"""
        mail = self.session.get(Mail, mail_id)
        if mail is None:
            raise LookupError(f"邮件不存在: {mail_id}")
        pending = [d for d in mail.drafts if d.status in {"pending_review", "draft", "approved"}]
        if not pending:
            raise LookupError("该邮件没有待发送的回复草稿")
        draft = max(pending, key=lambda d: d.id)
        return self.approve_draft(draft.id, reviewer_id=reviewer_id, body=body, actor=f"user:{reviewer_id}")

    # ------------------------------------------------------------ 规则试算
    def test_rules(
        self,
        *,
        raw: str | None = None,
        subject: str = "",
        from_addr: str = "",
        body: str = "",
    ) -> dict:
        """规则命中测试器（Phase 6）：只计算不落库，回答"为什么"。

        刻意不调用 LLM，保证结果稳定、可复现，便于运营调规则。
        """
        from mailmind.ml.classify import EmailClassifier
        from mailmind.ml.rules import RuleSet
        from mailmind.ml.spam import SpamFilter
        from mailmind.pipeline.features import build_features
        from mailmind.pipeline.parse import parse_message

        if raw:
            payload = raw.encode("utf-8")
        else:
            sender = from_addr or "test@example.com"
            payload = (
                f"From: {sender}\r\nTo: support@example.com\r\nSubject: {subject}\r\n"
                "Message-ID: <rule-test@mailmind.local>\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n\r\n" + body
            ).encode("utf-8")
        parsed = parse_message(payload)
        features = build_features(parsed)
        ruleset = RuleSet.from_db(self.session, None)
        hits = ruleset.evaluate(features)
        spam = SpamFilter(self.settings, ruleset, self.runtime.spam_model, None).evaluate(features)
        classification = EmailClassifier(
            self.settings, ruleset, self.runtime.category_model, None
        ).classify(features, is_spam=spam.label != "ham")
        return {
            "spam": spam.to_dict(),
            "classification": classification.to_dict(),
            "rule_hits": [hit.to_reason() for hit in hits],
            "features": {
                "from_addr": features.from_addr,
                "from_domain": features.from_domain,
                "subject": features.subject,
                "text_length": features.text_length,
                "url_domains": features.url_domains,
                "risky_attachments": features.risky_attachments,
                "auth": {"spf": features.spf, "dkim": features.dkim, "dmarc": features.dmarc},
                "sender_seen": features.sender_seen,
                "sender_spam_ratio": features.sender_spam_ratio,
            },
        }

    # ------------------------------------------------------------ 审计与反馈
    def list_audit(self, *, limit: int = 100, action: str | None = None) -> list[dict]:
        stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))
        if action:
            stmt = stmt.where(AuditLog.action.like(f"{action}%"))
        return [
            {
                "id": row.id,
                "actor": row.actor,
                "action": row.action,
                "target": row.target,
                "detail": row.detail,
                "trace_id": row.trace_id,
                "created_at": _iso(row.created_at),
            }
            for row in self.session.scalars(stmt).all()
        ]

    def list_feedback(
        self, *, mail_id: int | None = None, task: str | None = None, limit: int = 100
    ) -> list[dict]:
        stmt = select(Feedback).order_by(Feedback.id.desc()).limit(min(limit, 500))
        if mail_id is not None:
            stmt = stmt.where(Feedback.mail_id == mail_id)
        if task:
            stmt = stmt.where(Feedback.task == task)
        return [
            {
                "id": row.id,
                "mail_id": row.mail_id,
                "source": row.source,
                "task": row.task,
                "label": row.label,
                "note": row.note,
                "weight": row.weight,
                "created_at": _iso(row.created_at),
            }
            for row in self.session.scalars(stmt).all()
        ]

    # ------------------------------------------------------------ 统计
    def overview(self) -> dict:
        def count(stmt) -> int:
            return int(self.session.scalar(stmt) or 0)

        by_status = dict(
            self.session.execute(select(Mail.status, func.count()).group_by(Mail.status)).all()
        )
        by_category = dict(
            self.session.execute(
                select(MailVerdict.category, func.count()).group_by(MailVerdict.category)
            ).all()
        )
        by_spam_action = dict(
            self.session.execute(
                select(MailVerdict.spam_action, func.count()).group_by(MailVerdict.spam_action)
            ).all()
        )
        by_draft_status = dict(
            self.session.execute(
                select(ReplyDraft.status, func.count()).group_by(ReplyDraft.status)
            ).all()
        )
        total_mails = count(select(func.count()).select_from(Mail))
        spam_total = count(
            select(func.count())
            .select_from(MailVerdict)
            .where(MailVerdict.spam_label.in_(["spam", "phishing"]))
        )
        return {
            "mails_total": total_mails,
            "spam_total": spam_total,
            "spam_rate": round(spam_total / total_mails, 4) if total_mails else 0.0,
            "by_status": by_status,
            "by_category": by_category,
            "by_spam_action": by_spam_action,
            "drafts_by_status": by_draft_status,
            "quarantine_pending": count(
                select(func.count()).select_from(Mail).where(Mail.status == "quarantined")
            ),
            "review_pending": count(
                select(func.count())
                .select_from(ReplyDraft)
                .where(ReplyDraft.status == "pending_review")
            ),
            "feedback_total": count(select(func.count()).select_from(Feedback)),
            "generated_at": datetime.now(UTC).isoformat(),
        }
