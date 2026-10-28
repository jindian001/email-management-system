"""邮件接入与入库（exp.md 4.1/4.2）。

幂等键 = (account_id, message_id)，因此重复拉取、断点续传、重放都安全。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from mailmind.connectors.base import MailConnector
from mailmind.core.config import Settings
from mailmind.core.logging import get_logger
from mailmind.db.models import Account, Attachment, Mail
from mailmind.pipeline.parse import parse_message
from mailmind.pipeline.thread import thread_id_for
from mailmind.services import audit
from mailmind.services.processing import ProcessingService
from mailmind.services.runtime import Runtime
from mailmind.storage import content_key

log = get_logger("mailmind.ingest")


@dataclass
class IngestOutcome:
    status: str  # ingested | duplicate | error
    mail_id: int | None = None
    message_id: str = ""
    error: str = ""
    reply_status: str = "none"

    @property
    def ok(self) -> bool:
        return self.status == "ingested"


@dataclass
class SyncResult:
    fetched: int = 0
    ingested: int = 0
    duplicates: int = 0
    failed: int = 0
    reset: bool = False
    last_uid: int = 0
    uid_validity: int = 0

    def to_dict(self) -> dict:
        return {
            "fetched": self.fetched,
            "ingested": self.ingested,
            "duplicates": self.duplicates,
            "failed": self.failed,
            "reset": self.reset,
            "last_uid": self.last_uid,
            "uid_validity": self.uid_validity,
        }


class IngestService:
    def __init__(self, settings: Settings, session: Session, runtime: Runtime) -> None:
        self.settings = settings
        self.session = session
        self.runtime = runtime

    # ------------------------------------------------------------ 单封邮件
    def ingest_raw(
        self,
        account: Account,
        raw: bytes,
        *,
        folder: str = "INBOX",
        uid: str = "",
        commit: bool = True,
    ) -> IngestOutcome:
        if len(raw) > self.settings.max_mail_bytes:
            return IngestOutcome("error", error="too_large")
        if not raw.strip():
            return IngestOutcome("error", error="empty")

        parsed = parse_message(raw)

        existing = self.session.scalar(
            select(Mail).where(
                Mail.account_id == account.id, Mail.message_id == parsed.message_id
            )
        )
        if existing is not None:
            return IngestOutcome("duplicate", existing.id, parsed.message_id)

        key = content_key(raw)
        try:
            self.runtime.store.put(key, raw)
        except OSError as exc:  # pragma: no cover - 存储不可用
            return IngestOutcome("error", parsed.message_id, error=f"storage:{exc}")

        mail = Mail(
            account_id=account.id,
            message_id=parsed.message_id,
            thread_id=thread_id_for(parsed),
            folder=folder,
            uid=int(uid) if str(uid).isdigit() else 0,
            imap_uid=str(uid),
            from_addr=parsed.from_addr,
            from_name=parsed.from_name,
            to_addrs=parsed.to_addrs,
            cc_addrs=parsed.cc_addrs,
            reply_to=parsed.reply_to,
            subject=parsed.subject,
            sent_at=parsed.sent_at,
            received_at=datetime.now(UTC),
            size_bytes=parsed.size_bytes,
            has_attachment=parsed.has_attachment,
            raw_object_key=key,
            text_body=parsed.text_body,
            headers=parsed.headers,
            status="parsed",
        )
        self.session.add(mail)
        self.session.flush()

        self._store_attachments(mail, parsed)

        result = ProcessingService(self.settings, self.session, self.runtime).process(mail, parsed)
        audit.record(
            self.session,
            actor="system:ingest",
            action="mail.ingested",
            target=f"mail:{mail.id}",
            detail={
                "message_id": parsed.message_id,
                "folder": folder,
                "spam_action": result.spam.action,
                "category": result.classification.category,
            },
        )
        if commit:
            self.session.commit()

        return IngestOutcome(
            "ingested",
            mail.id,
            parsed.message_id,
            reply_status=result.reply_status,
        )

    def _store_attachments(self, mail: Mail, parsed) -> None:
        for att in parsed.attachments:
            object_key = ""
            if att.data and att.size_bytes <= self.settings.max_attachment_bytes:
                object_key = content_key(att.data, prefix="attach")
                try:
                    self.runtime.store.put(object_key, att.data)
                except OSError:  # pragma: no cover
                    object_key = ""
            self.session.add(
                Attachment(
                    mail_id=mail.id,
                    filename=att.filename,
                    content_type=att.content_type,
                    size_bytes=att.size_bytes,
                    sha256=att.sha256,
                    object_key=object_key,
                    is_risky=att.is_risky,
                )
            )

    # ------------------------------------------------------------ 批量同步
    def sync_account(
        self, account: Account, connector: MailConnector, limit: int = 100
    ) -> SyncResult:
        page = connector.fetch_since(account.last_uid, account.uid_validity, limit)
        result = SyncResult(reset=page.reset, uid_validity=page.uid_validity)

        if page.reset:
            log.info("uidvalidity_reset", account=account.id, old=account.uid_validity, new=page.uid_validity)

        for message in page.messages:
            result.fetched += 1
            outcome = self.ingest_raw(
                account, message.raw, folder=message.folder, uid=message.uid, commit=False
            )
            if outcome.status == "ingested":
                result.ingested += 1
            elif outcome.status == "duplicate":
                result.duplicates += 1
            else:
                result.failed += 1
                log.warning("ingest_failed", uid=message.uid, error=outcome.error)

        account.uid_validity = page.uid_validity or account.uid_validity
        if page.last_uid:
            account.last_uid = page.last_uid
        account.last_synced_at = datetime.now(UTC)
        result.last_uid = account.last_uid
        result.uid_validity = account.uid_validity
        self.session.commit()
        return result
