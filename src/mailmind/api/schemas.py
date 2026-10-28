"""请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AccountIn(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    provider: Literal["imap", "gmail", "graph", "memory"] = "imap"
    display_name: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    secret: str = ""


class AccountPatch(BaseModel):
    """部分更新：只传要改的字段。

    典型用途：Gmail/Graph 的 access token 过期后回写、邮箱改密码、暂停账号。
    """

    display_name: str | None = None
    config: dict[str, Any] | None = None
    secret: str | None = None
    status: Literal["active", "paused"] | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    provider: str
    display_name: str
    status: str
    last_uid: int
    uid_validity: int
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class IngestIn(BaseModel):
    raw: str = Field(description="原始邮件文本（utf-8）或 base64")
    base64: bool = False
    folder: str = "INBOX"
    uid: str = ""


class IngestOut(BaseModel):
    status: str
    mail_id: int | None = None
    message_id: str = ""
    error: str = ""
    reply_status: str = "none"


class FeedbackIn(BaseModel):
    task: Literal["spam", "category", "reply_quality"]
    label: dict[str, Any]
    note: str = ""
    source: Literal["user", "reviewer", "rule", "model"] = "user"


class RuleIn(BaseModel):
    kind: Literal[
        "allowlist",
        "blocklist",
        "keyword",
        "header",
        "auth",
        "sender_reputation",
        "category",
        "subject_regex",
    ]
    action: Literal["spam", "ham", "tag", "route"] = "spam"
    payload: dict[str, Any] = Field(default_factory=dict)
    scope: Literal["global", "account", "domain"] = "global"
    scope_id: str = ""
    priority: int = 100
    enabled: bool = True
    description: str = ""


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    action: str
    payload: dict[str, Any]
    scope: str
    scope_id: str
    priority: int
    enabled: bool
    description: str


class KbIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    source: Literal["faq", "manual", "past_ticket"] = "faq"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApproveIn(BaseModel):
    reviewer_id: str = Field(min_length=1, max_length=64)
    body: str | None = None


class SendReplyIn(BaseModel):
    reviewer_id: str = Field(min_length=1, max_length=64)
    body: str | None = None


class RuleTestIn(BaseModel):
    raw: str | None = None
    subject: str = ""
    from_addr: str = ""
    body: str = ""


class RejectIn(BaseModel):
    reviewer_id: str = Field(min_length=1, max_length=64)
    reason: str = ""


class SyncOut(BaseModel):
    fetched: int
    ingested: int
    duplicates: int
    failed: int
    reset: bool
    last_uid: int
    uid_validity: int
