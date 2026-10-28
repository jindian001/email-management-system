"""特征工程。

一个 ``FeatureBundle`` 供规则引擎、L1 模型和 LLM 复核共用，
保证三处看到的是同一份事实（exp.md 4.4）。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from mailmind.pipeline.normalize import (
    UrlInfo,
    dense_feature_hint,
    deobfuscate,
    extract_urls,
    normalize_text,
)
from mailmind.pipeline.parse import ParsedMail

URGENCY_WORDS = [
    "urgent", "immediately", "act now", "limited time", "winner", "congratulations",
    "claim now", "free gift", "risk-free", "guaranteed", "no cost", "click here",
    "verify your account", "中奖", "恭喜", "立即领取", "限时", "免费", "秒杀", "返现",
    "贷款", "刷单", "代开", "发票", "赌场", "博彩", "内部消息",
]


@dataclass
class SenderStats:
    seen_count: int = 0
    spam_count: int = 0
    first_seen: datetime | None = None
    is_contact: bool = False

    @property
    def spam_ratio(self) -> float:
        return self.spam_count / self.seen_count if self.seen_count else 0.0


@dataclass
class FeatureBundle:
    # 身份
    from_addr: str = ""
    from_domain: str = ""
    from_name: str = ""
    reply_to: str = ""
    return_path: str = ""
    message_id: str = ""
    list_id: str = ""
    # 头部异常
    reply_to_mismatch: bool = False
    return_path_mismatch: bool = False
    message_id_domain_mismatch: bool = False
    missing_received: bool = False
    received_hops: int = 0
    date_in_future: bool = False
    suspicious_display_name: bool = False
    # 认证
    spf: str = "none"
    dkim: str = "none"
    dmarc: str = "none"
    auth_failures: int = 0
    # 发件人信誉
    sender_seen: int = 0
    sender_spam_ratio: float = 0.0
    sender_first_seen_hours: float | None = None
    # 内容
    subject: str = ""
    text: str = ""
    normalized_text: str = ""  # 反混淆后
    headers: dict[str, str] = field(default_factory=dict)
    text_length: int = 0
    caps_ratio: float = 0.0
    exclamations: float = 0.0
    currency_hits: float = 0.0
    urgency_hits: int = 0
    html_image_count: int = 0
    html_only: bool = False
    # URL
    url_count: int = 0
    url_domains: list[str] = field(default_factory=list)
    ip_urls: int = 0
    shortener_urls: int = 0
    punycode_urls: int = 0
    # 附件
    attachment_count: int = 0
    risky_attachments: list[str] = field(default_factory=list)
    # 会话
    is_reply: bool = False
    references_count: int = 0
    is_bulk: bool = False
    is_auto_submitted: bool = False
    to_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _domain_of(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].lower() if addr and "@" in addr else ""


def ensure_utc(value: datetime | None) -> datetime | None:
    """SQLite 读回来的是 naive datetime，统一按 UTC 处理（exp.md 附录 C.2）。"""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _domain_of_header(value: str) -> str:
    match = re.search(r"[\w.+-]+@([\w.-]+)", value or "")
    return match.group(1).lower() if match else ""


def build_features(
    parsed: ParsedMail,
    sender_stats: SenderStats | None = None,
    now: datetime | None = None,
) -> FeatureBundle:
    now = now or datetime.now(UTC)
    stats = sender_stats or SenderStats()

    subject = normalize_text(parsed.subject)
    body = normalize_text(parsed.text_body)
    combined = f"{subject}\n{body}"
    deob = deobfuscate(combined)
    urls: list[UrlInfo] = extract_urls(combined)
    hints = dense_feature_hint(combined)

    lowered = deob.lower()
    urgency_hits = sum(1 for word in URGENCY_WORDS if word in lowered)

    from_domain = _domain_of(parsed.from_addr)
    reply_to_domain = _domain_of_header(parsed.reply_to)
    return_path_domain = _domain_of_header(parsed.return_path)
    message_id_domain = _domain_of_header(parsed.message_id)

    auth_failures = sum(1 for v in parsed.auth_results.values() if v == "fail")

    display_name = (parsed.from_name or "").lower()
    suspicious_name = bool(
        display_name
        and (
            "@" in display_name
            or re.search(r"(support|admin|security|service|财务|银行|客服)", display_name)
            and from_domain
            and not from_domain.endswith(("bank", "gov", "edu"))
        )
    )

    return FeatureBundle(
        from_addr=parsed.from_addr,
        from_domain=from_domain,
        from_name=parsed.from_name,
        reply_to=parsed.reply_to,
        return_path=parsed.return_path,
        message_id=parsed.message_id,
        list_id=parsed.list_id,
        reply_to_mismatch=bool(reply_to_domain and reply_to_domain != from_domain),
        return_path_mismatch=bool(return_path_domain and return_path_domain != from_domain),
        message_id_domain_mismatch=bool(
            message_id_domain and from_domain and message_id_domain != from_domain
        ),
        missing_received=parsed.received_count == 0,
        received_hops=parsed.received_count,
        date_in_future=bool(parsed.sent_at and parsed.sent_at > now + timedelta(days=1)),
        suspicious_display_name=suspicious_name,
        spf=parsed.auth_results.get("spf", "none"),
        dkim=parsed.auth_results.get("dkim", "none"),
        dmarc=parsed.auth_results.get("dmarc", "none"),
        auth_failures=auth_failures,
        sender_seen=stats.seen_count,
        sender_spam_ratio=round(stats.spam_ratio, 4),
        sender_first_seen_hours=(
            round((now - ensure_utc(stats.first_seen)).total_seconds() / 3600, 2)
            if stats.first_seen
            else None
        ),
        subject=subject,
        text=body,
        normalized_text=deob,
        headers=dict(parsed.headers),
        text_length=len(combined),
        caps_ratio=hints["caps_ratio"],
        exclamations=hints["exclamations"],
        currency_hits=hints["currency"],
        urgency_hits=urgency_hits,
        html_image_count=parsed.html_body.lower().count("<img"),
        html_only=bool(parsed.html_body and not parsed.text_body.strip()),
        url_count=len(urls),
        url_domains=sorted({u.host for u in urls}),
        ip_urls=sum(1 for u in urls if u.is_ip),
        shortener_urls=sum(1 for u in urls if u.is_shortener),
        punycode_urls=sum(1 for u in urls if u.has_punycode),
        attachment_count=len(parsed.attachments),
        risky_attachments=[a.filename for a in parsed.attachments if a.is_risky],
        is_reply=bool(parsed.in_reply_to or parsed.references),
        references_count=len(parsed.references),
        is_bulk=_is_bulk(parsed),
        is_auto_submitted=bool(parsed.auto_submitted and parsed.auto_submitted.lower() != "no"),
        to_count=len(parsed.to_addrs) + len(parsed.cc_addrs),
    )


def _is_bulk(parsed: ParsedMail) -> bool:
    precedence = (parsed.precedence or "").lower()
    return precedence in {"bulk", "list", "junk"} or bool(parsed.list_id)
