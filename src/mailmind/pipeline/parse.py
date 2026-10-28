"""MIME 解析：把原始字节变成结构化 :class:`ParsedMail`。

只用标准库 ``email``（policy.default），不自己造轮子。所有函数纯函数、可单测。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.message import Message
from email.parser import BytesParser
from email.policy import default as default_policy
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

RISKY_EXTENSIONS = {
    "exe", "scr", "js", "jse", "vbs", "vbe", "bat", "cmd", "com", "pif",
    "lnk", "hta", "msi", "jar", "ps1", "iso", "img", "docm", "xlsm", "pptm",
}

_SUBJECT_PREFIX_RE = re.compile(
    r"^\s*(?:(?:re|fw|fwd|aw|sv|回复|答复|转发)\s*[:：]\s*)+", re.I
)
_AUTH_RE = re.compile(r"\b(spf|dkim|dmarc|compauth)\s*=\s*([a-zA-Z]+)", re.I)
_ENCODED_RE = re.compile(r"=\?([\w\-]+)\?([bBqQ])\?([^?]*)\?=")


@dataclass
class ParsedAttachment:
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    data: bytes
    content_id: str = ""
    is_inline: bool = False
    is_risky: bool = False


@dataclass
class ParsedMail:
    message_id: str
    subject: str
    from_addr: str
    from_name: str
    to_addrs: list[str] = field(default_factory=list)
    cc_addrs: list[str] = field(default_factory=list)
    reply_to: str = ""
    sent_at: datetime | None = None
    text_body: str = ""
    html_body: str = ""
    attachments: list[ParsedAttachment] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    raw_headers: dict[str, list[str]] = field(default_factory=dict)
    references: list[str] = field(default_factory=list)
    in_reply_to: str = ""
    list_id: str = ""
    precedence: str = ""
    auto_submitted: str = ""
    return_path: str = ""
    received_count: int = 0
    auth_results: dict[str, str] = field(default_factory=dict)
    size_bytes: int = 0
    parse_warnings: list[str] = field(default_factory=list)

    @property
    def has_attachment(self) -> bool:
        return bool(self.attachments)

    @property
    def has_risky_attachment(self) -> bool:
        return any(a.is_risky for a in self.attachments)

    @property
    def from_domain(self) -> str:
        return self.from_addr.rsplit("@", 1)[-1].lower() if "@" in self.from_addr else ""


# ---------------------------------------------------------------- 工具


class _HTMLToText(HTMLParser):
    SKIP = {"script", "style", "head", "noscript"}
    BLOCK = {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "table", "section", "article", "blockquote", "ul", "ol",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    if not html:
        return ""
    parser = _HTMLToText()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - 畸形 HTML 兜底
        return re.sub(r"<[^>]+>", " ", html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def decode_bytes(data: bytes, charset: str | None = None) -> str:
    candidates = [charset, "utf-8", "gb18030", "big5", "latin-1"]
    for enc in candidates:
        if not enc:
            continue
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def safe_header(msg: Message, name: str) -> str:
    value = msg.get(name)
    if value is None:
        return ""
    try:
        return str(make_header(decode_header(str(value))))
    except Exception:  # noqa: BLE001 - 编码畸形时保留原样
        return str(value)


def normalize_subject(subject: str) -> str:
    subject = _SUBJECT_PREFIX_RE.sub("", subject or "")
    return re.sub(r"\s+", " ", subject).strip()


def parse_references(value: str) -> list[str]:
    return [part.strip("<>") for part in (value or "").split() if part.strip("<>")]


def parse_auth_results(headers: dict[str, list[str]]) -> dict[str, str]:
    """解析 Authentication-Results（取最靠近接收端的一条）。"""
    results: dict[str, str] = {}
    for value in headers.get("authentication-results", []):
        for mechanism, result in _AUTH_RE.findall(value):
            key = mechanism.lower()
            if key not in results:
                results[key] = result.lower()
    return results


def is_risky_filename(filename: str) -> bool:
    name = (filename or "").strip().lower().replace(" ", "")
    if not name:
        return False
    parts = name.rsplit(".", 1)
    if len(parts) != 2:
        return False
    ext = parts[1]
    if ext in RISKY_EXTENSIONS:
        return True
    # 双扩展名 invoice.pdf.exe 已经被上面捕获；这里额外识别 .pdf.zip 之类
    return "." in parts[0] and parts[0].rsplit(".", 1)[-1] in RISKY_EXTENSIONS


def _part_payload(part: Message) -> bytes:
    try:
        payload = part.get_payload(decode=True)
    except Exception:  # noqa: BLE001
        payload = None
    if payload is None:
        raw = part.get_payload()
        if isinstance(raw, str):
            return raw.encode("utf-8", "replace")
        return b""
    return payload


def _part_text(part: Message) -> str:
    data = _part_payload(part)
    return decode_bytes(data, part.get_content_charset())


def _first_recipients(msg: Message, header: str) -> list[str]:
    from email.utils import getaddresses

    values = msg.get_all(header) or []
    out: list[str] = []
    for _name, addr in getaddresses([str(v) for v in values]):
        if addr:
            out.append(addr)
    return out


def parse_message(raw: bytes) -> ParsedMail:
    """解析原始邮件字节。绝不抛异常——解析失败会写入 parse_warnings。"""
    warnings: list[str] = []
    try:
        msg = BytesParser(policy=default_policy).parsebytes(raw)
    except Exception as exc:  # noqa: BLE001
        msg = None
        warnings.append(f"parse_error:{exc}")

    if msg is None:
        return ParsedMail(
            message_id=f"<{hashlib.sha256(raw).hexdigest()[:32]}@mailmind.local>",
            subject="",
            from_addr="",
            size_bytes=len(raw),
            parse_warnings=warnings,
        )

    headers: dict[str, str] = {}
    raw_headers: dict[str, list[str]] = {}
    for key, value in msg.items():
        lk = key.lower()
        try:
            sv = str(make_header(decode_header(str(value))))
        except Exception:  # noqa: BLE001
            sv = str(value)
        headers.setdefault(lk, sv)
        raw_headers.setdefault(lk, []).append(sv)

    from_header = safe_header(msg, "From")
    from_pairs = _parse_from(from_header)
    from_name, from_addr = from_pairs

    message_id_header = safe_header(msg, "Message-ID").strip()
    message_id = message_id_header.strip("<>") if message_id_header else ""
    if not message_id:
        message_id = f"{hashlib.sha256(raw).hexdigest()[:32]}@mailmind.local"

    sent_at: datetime | None = None
    date_header = safe_header(msg, "Date")
    if date_header:
        try:
            sent_at = parsedate_to_datetime(date_header)
            if sent_at and sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=UTC)
            if sent_at:
                sent_at = sent_at.astimezone(UTC)
        except Exception:  # noqa: BLE001
            warnings.append("bad_date")

    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[ParsedAttachment] = []

    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        content_type = part.get_content_type()
        filename = part.get_filename()
        filename = str(make_header(decode_header(filename))) if filename else ""
        disposition = (part.get_content_disposition() or "").lower()

        if filename or disposition == "attachment":
            data = _part_payload(part)
            attachments.append(
                ParsedAttachment(
                    filename=filename or "unnamed",
                    content_type=content_type,
                    size_bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    data=data,
                    content_id=str(part.get("Content-ID") or "").strip("<>"),
                    is_inline=disposition == "inline",
                    is_risky=is_risky_filename(filename),
                )
            )
            continue

        if content_type == "text/plain":
            text_parts.append(_part_text(part))
        elif content_type == "text/html":
            html_parts.append(_part_text(part))

    text_body = "\n".join(t for t in text_parts if t.strip()).strip()
    html_body = "\n".join(h for h in html_parts if h.strip()).strip()
    if not text_body and html_body:
        text_body = html_to_text(html_body)

    received = raw_headers.get("received", [])

    return ParsedMail(
        message_id=message_id,
        subject=safe_header(msg, "Subject"),
        from_addr=from_addr,
        from_name=from_name,
        to_addrs=_first_recipients(msg, "To"),
        cc_addrs=_first_recipients(msg, "Cc"),
        reply_to=safe_header(msg, "Reply-To"),
        sent_at=sent_at,
        text_body=text_body,
        html_body=html_body,
        attachments=attachments,
        headers=headers,
        raw_headers=raw_headers,
        references=parse_references(safe_header(msg, "References")),
        in_reply_to=parse_references(safe_header(msg, "In-Reply-To"))[:1],
        list_id=safe_header(msg, "List-Id"),
        precedence=safe_header(msg, "Precedence"),
        auto_submitted=safe_header(msg, "Auto-Submitted"),
        return_path=safe_header(msg, "Return-Path"),
        received_count=len(received),
        auth_results=parse_auth_results(raw_headers),
        size_bytes=len(raw),
        parse_warnings=warnings,
    )


def _parse_from(header: str) -> tuple[str, str]:
    from email.utils import parseaddr

    name, addr = parseaddr(header or "")
    if not addr:
        # 兜底：解析失败时尽量抠出形如 a@b.c 的片段
        match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", header or "")
        addr = match.group(0) if match else ""
    return name.strip(), addr.lower()
