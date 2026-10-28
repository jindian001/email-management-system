"""SQLAlchemy ORM 模型。

设计原则（见 exp.md 4.2）：
- ``mails`` 只存元数据与正文，原始 EML 落在对象存储；
- 判定结果独立成表，便于模型版本回放；
- 所有数组/结构字段用 JSON，保证 SQLite（测试）与 PostgreSQL（生产）同样可用。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="imap")  # imap | gmail | graph
    display_name: Mapped[str] = mapped_column(String(128), default="")
    # 连接参数；密码/token 必须已加密（生产环境由 KMS 提供密钥）
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    secret_enc: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active")
    last_uid: Mapped[int] = mapped_column(Integer, default=0)
    uid_validity: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    mails: Mapped[list[Mail]] = relationship(back_populates="account", cascade="all, delete-orphan")


class Mail(Base, TimestampMixin):
    __tablename__ = "mails"
    __table_args__ = (
        UniqueConstraint("account_id", "message_id", name="uq_mail_account_message"),
        Index("ix_mails_account_received", "account_id", "received_at"),
        Index("ix_mails_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    message_id: Mapped[str] = mapped_column(String(512), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(512), default="")
    folder: Mapped[str] = mapped_column(String(128), default="INBOX")
    uid: Mapped[int] = mapped_column(Integer, default=0)
    imap_uid: Mapped[str] = mapped_column(String(64), default="")

    from_addr: Mapped[str] = mapped_column(String(320), default="")
    from_name: Mapped[str] = mapped_column(String(256), default="")
    to_addrs: Mapped[list] = mapped_column(JSON, default=list)
    cc_addrs: Mapped[list] = mapped_column(JSON, default=list)
    reply_to: Mapped[str] = mapped_column(String(320), default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    has_attachment: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_object_key: Mapped[str] = mapped_column(String(512), default="")
    html_object_key: Mapped[str] = mapped_column(String(512), default="")
    text_body: Mapped[str] = mapped_column(Text, default="")
    headers: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="fetched")
    error: Mapped[str] = mapped_column(Text, default="")

    account: Mapped[Account] = relationship(back_populates="mails")
    verdict: Mapped[MailVerdict | None] = relationship(
        back_populates="mail", uselist=False, cascade="all, delete-orphan"
    )
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="mail", cascade="all, delete-orphan"
    )
    drafts: Mapped[list[ReplyDraft]] = relationship(
        back_populates="mail", cascade="all, delete-orphan"
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mails.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(512), default="")
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    object_key: Mapped[str] = mapped_column(String(512), default="")
    is_risky: Mapped[bool] = mapped_column(Boolean, default=False)

    mail: Mapped[Mail] = relationship(back_populates="attachments")


class MailVerdict(Base):
    __tablename__ = "mail_verdicts"

    mail_id: Mapped[int] = mapped_column(
        ForeignKey("mails.id", ondelete="CASCADE"), primary_key=True
    )
    spam_score: Mapped[float] = mapped_column(Float, default=0.0)
    spam_label: Mapped[str] = mapped_column(String(16), default="ham")  # ham | spam | phishing
    spam_action: Mapped[str] = mapped_column(String(16), default="pass")  # pass | tag | quarantine
    spam_reasons: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str] = mapped_column(String(32), default="other")
    category_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    category_reason: Mapped[dict] = mapped_column(JSON, default=dict)
    model_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    mail: Mapped[Mail] = relationship(back_populates="verdict")


class Rule(Base, TimestampMixin):
    __tablename__ = "rules"
    __table_args__ = (Index("ix_rules_scope", "scope", "scope_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), default="global")  # global | account | domain
    scope_id: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(32), default="keyword")
    # kind: blocklist | allowlist | keyword | header | sender_reputation | auth
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    action: Mapped[str] = mapped_column(String(16), default="spam")  # spam | ham | tag | route
    priority: Mapped[int] = mapped_column(Integer, default=100)  # 数字越小优先级越高
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    description: Mapped[str] = mapped_column(Text, default="")


class ReplyDraft(Base):
    __tablename__ = "reply_drafts"
    __table_args__ = (Index("ix_drafts_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mails.id", ondelete="CASCADE"))
    intent: Mapped[str] = mapped_column(String(32), default="other")
    subject: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # draft | pending_review | approved | rejected | sent | failed
    status: Mapped[str] = mapped_column(String(32), default="draft")
    model: Mapped[str] = mapped_column(String(64), default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    reviewer_id: Mapped[str] = mapped_column(String(64), default="")
    edited_diff: Mapped[str] = mapped_column(Text, default="")
    risk_flags: Mapped[list] = mapped_column(JSON, default=list)
    provider_message_id: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    mail: Mapped[Mail] = relationship(back_populates="drafts")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mails.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32), default="user")  # user | reviewer | rule | model
    task: Mapped[str] = mapped_column(String(32), default="spam")  # spam | category | reply_quality
    label: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeDocument(Base):
    __tablename__ = "kb_documents"
    __table_args__ = (Index("ix_kb_source", "source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="faq")  # faq | manual | past_ticket
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    doc_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(128), default="system")
    action: Mapped[str] = mapped_column(String(64), default="")
    target: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
