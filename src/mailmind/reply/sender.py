"""回复发送：组装 MIME、写入发送记录、冷却期与审计（exp.md 4.7.4）。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from mailmind.connectors.base import MessageSender, OutgoingMessage, SendError
from mailmind.db.models import Account, Mail, ReplyDraft
from mailmind.reply.policy import ReplyPolicy


@dataclass
class SendOutcome:
    ok: bool
    status: str
    provider_message_id: str = ""
    error: str = ""


def build_outgoing(
    *,
    account: Account,
    mail: Mail,
    subject: str,
    body_text: str,
    in_reply_to: str = "",
    references: list[str] | None = None,
) -> OutgoingMessage:
    refs = list(references or [])
    if mail.message_id not in refs:
        refs.append(mail.message_id)
    return OutgoingMessage(
        to=[mail.from_addr] if mail.from_addr else [],
        subject=subject,
        body_text=body_text,
        from_addr=account.email,
        in_reply_to=f"<{mail.message_id}>" if mail.message_id else "",
        references=[f"<{r.strip('<>')}>" for r in refs],
        headers={"Message-ID": f"<{uuid.uuid4().hex}@mailmind.local>"},
        in_reply_to_uid=mail.message_id,
    )


class ReplySenderService:
    def __init__(self, settings, session: Session, sender: MessageSender, policy: ReplyPolicy) -> None:
        self.settings = settings
        self.session = session
        self.sender = sender
        self.policy = policy

    def send_draft(
        self,
        draft: ReplyDraft,
        *,
        account: Account,
        mail: Mail,
        actor: str = "system:auto-reply",
        override_body: str | None = None,
    ) -> SendOutcome:
        body = override_body if override_body is not None else draft.body
        if not body.strip():
            return SendOutcome(False, "rejected", error="empty_body")

        references = _references_from_mail(mail)
        message = build_outgoing(
            account=account,
            mail=mail,
            subject=draft.subject or f"Re: {mail.subject}",
            body_text=body,
            references=references,
        )
        try:
            provider_id = self.sender.send(account.email, message)
        except SendError as exc:
            draft.status = "failed"
            self.session.flush()
            self._audit(actor, "reply.failed", draft, {"error": str(exc)})
            return SendOutcome(False, "failed", error=str(exc))

        draft.status = "sent"
        draft.provider_message_id = provider_id
        draft.body = body
        self.policy.mark_sent(mail.account_id, mail.from_addr)
        mail.status = "replied"
        self.session.flush()
        self._audit(actor, "reply.sent", draft, {"provider_message_id": provider_id})
        return SendOutcome(True, "sent", provider_message_id=provider_id)

    def approve_and_send(
        self,
        draft: ReplyDraft,
        *,
        account: Account,
        mail: Mail,
        reviewer_id: str,
        body: str | None = None,
    ) -> SendOutcome:
        if draft.status not in {"pending_review", "draft", "approved"}:
            return SendOutcome(False, draft.status, error=f"状态 {draft.status} 不可发送")
        if body is not None and body.strip() != (draft.body or "").strip():
            draft.edited_diff = _diff_summary(draft.body, body)
        draft.reviewer_id = reviewer_id
        draft.status = "approved"
        self.session.flush()
        return self.send_draft(
            draft,
            account=account,
            mail=mail,
            actor=f"user:{reviewer_id}",
            override_body=body,
        )

    def _audit(self, actor: str, action: str, draft: ReplyDraft, detail: dict) -> None:
        from mailmind.db.models import AuditLog

        self.session.add(
            AuditLog(
                actor=actor,
                action=action,
                target=f"reply_draft:{draft.id}",
                detail={
                    "mail_id": draft.mail_id,
                    "status": draft.status,
                    "model": draft.model,
                    "at": datetime.now(UTC).isoformat(),
                    **detail,
                },
            )
        )


def _references_from_mail(mail: Mail) -> list[str]:
    raw = (mail.headers or {}).get("references", "")
    return [part.strip("<>") for part in raw.replace(",", " ").split() if part.strip("<>")]


def _diff_summary(original: str, edited: str) -> str:
    """记录人工编辑的摘要，供后续评估"草稿可用率"。"""
    return f"original_len={len(original or '')} edited_len={len(edited or '')}"
