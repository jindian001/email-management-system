"""邮件接入层。

对外只暴露 :class:`MailConnector` 协议（exp.md 4.1），IMAP / Gmail / Graph 各自实现，
上层服务完全无感。同步发信用 :class:`MessageSender`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

# ---------------------------------------------------------------- 数据模型


@dataclass
class Folder:
    name: str
    delimiter: str = "/"
    flags: list[str] = field(default_factory=list)


@dataclass
class FetchedMessage:
    uid: str
    raw: bytes
    folder: str = "INBOX"
    flags: list[str] = field(default_factory=list)


@dataclass
class FetchPage:
    messages: list[FetchedMessage]
    uid_validity: int
    last_uid: int
    reset: bool = False  # True 表示 UIDVALIDITY 变化，需要全量重扫


@dataclass
class OutgoingMessage:
    to: list[str]
    subject: str
    body_text: str
    body_html: str = ""
    from_addr: str = ""
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    in_reply_to_uid: str = ""


class ConnectorError(RuntimeError):
    pass


class SendError(RuntimeError):
    pass


# ---------------------------------------------------------------- 协议


class MailConnector(Protocol):
    def list_folders(self) -> list[Folder]: ...
    def fetch_since(self, last_uid: int, uid_validity: int, limit: int = 100) -> FetchPage: ...
    def close(self) -> None: ...


class MessageSender(Protocol):
    def send(self, account_email: str, message: OutgoingMessage) -> str: ...


# ---------------------------------------------------------------- 内存实现


class MemoryConnector:
    """内存连接器：测试与演示用，可预置邮件并模拟 UIDVALIDITY 变化。"""

    def __init__(self, messages: list[FetchedMessage] | None = None, uid_validity: int = 1) -> None:
        self._messages = list(messages or [])
        self.uid_validity = uid_validity
        self.closed = False
        self._next_uid = max((int(m.uid) for m in self._messages), default=0) + 1

    def add(self, raw: bytes, folder: str = "INBOX") -> FetchedMessage:
        msg = FetchedMessage(uid=str(self._next_uid), raw=raw, folder=folder)
        self._next_uid += 1
        self._messages.append(msg)
        return msg

    def list_folders(self) -> list[Folder]:
        return [Folder("INBOX")]

    def fetch_since(self, last_uid: int, uid_validity: int, limit: int = 100) -> FetchPage:
        reset = uid_validity not in (0, self.uid_validity)
        candidates = [
            m
            for m in self._messages
            if int(m.uid) > (0 if reset else last_uid)
        ]
        candidates.sort(key=lambda m: int(m.uid))
        page = candidates[:limit]
        new_last = int(page[-1].uid) if page else (0 if reset else last_uid)
        return FetchPage(
            messages=page,
            uid_validity=self.uid_validity,
            last_uid=new_last,
            reset=reset,
        )

    def close(self) -> None:
        self.closed = True


class RecordingSender:
    """记录发出的邮件，测试断言用。"""

    def __init__(self) -> None:
        self.sent: list[tuple[str, OutgoingMessage]] = []

    def send(self, account_email: str, message: OutgoingMessage) -> str:
        self.sent.append((account_email, message))
        return f"<sent-{len(self.sent)}@mailmind.local>"


class FailingSender:
    def __init__(self, error: str = "smtp unavailable") -> None:
        self.error = error
        self.calls = 0

    def send(self, account_email: str, message: OutgoingMessage) -> str:
        self.calls += 1
        raise SendError(self.error)


# ---------------------------------------------------------------- MIME 构造


def build_mime(message: OutgoingMessage, account_email: str) -> EmailMessage:
    """把 OutgoingMessage 转成标准 MIME。

    依据 RFC 3834，自动回复必须带 ``Auto-Submitted: auto-replied``，
    否则会与对方的自动回复形成回环。
    """
    if not message.to:
        raise ValueError("收件人不能为空")
    msg = EmailMessage()
    msg["From"] = message.from_addr or account_email
    msg["To"] = ", ".join(message.to)
    msg["Subject"] = message.subject
    msg["Auto-Submitted"] = "auto-replied"
    msg["X-Mailer"] = "MailMind/0.1"
    if message.in_reply_to:
        msg["In-Reply-To"] = message.in_reply_to
    if message.references:
        msg["References"] = " ".join(message.references)
    for key, value in message.headers.items():
        msg[key] = value

    msg.set_content(message.body_text or "")
    if message.body_html:
        msg.add_alternative(message.body_html, subtype="html")
    return msg


def parse_address_list(value: str | None) -> list[str]:
    if not value:
        return []
    from email.utils import getaddresses

    return [addr for _name, addr in getaddresses([value]) if addr]


def is_auto_submitted(headers: dict[str, str]) -> bool:
    """RFC 3834：Auto-Submitted 只要不是 no，就说明是自动发出的。"""
    value = (headers.get("auto-submitted") or "").strip().lower()
    return bool(value) and value != "no"


def is_bulk(headers: dict[str, str]) -> bool:
    precedence = (headers.get("precedence") or "").strip().lower()
    if precedence in {"bulk", "list", "junk"}:
        return True
    return bool(headers.get("list-id") or headers.get("list-unsubscribe"))


def thread_depth(references: list[str], in_reply_to: str = "") -> int:
    ids = {r for r in references if r}
    if in_reply_to:
        ids.add(in_reply_to)
    return len(ids)


__all__ = [
    "ConnectorError",
    "FetchPage",
    "FetchedMessage",
    "Folder",
    "MailConnector",
    "MemoryConnector",
    "MessageSender",
    "OutgoingMessage",
    "RecordingSender",
    "SendError",
    "build_mime",
    "is_auto_submitted",
    "is_bulk",
    "parse_address_list",
    "thread_depth",
]
