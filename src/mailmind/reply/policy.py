"""自动回复放行策略（exp.md 4.7.1）。

这里是全系统风险最高的闸门：宁可少回，不可回错、不可回环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from mailmind.connectors.base import is_auto_submitted, is_bulk, thread_depth
from mailmind.core.config import Settings


@dataclass
class ReplyContext:
    account_id: int
    from_addr: str
    subject: str
    headers: dict[str, str] = field(default_factory=dict)
    references: list[str] = field(default_factory=list)
    in_reply_to: list[str] = field(default_factory=list)
    category: str = "other"
    spam_label: str = "ham"
    has_risky_attachment: bool = False
    received_at: datetime | None = None

    @property
    def thread_depth(self) -> int:
        return thread_depth(self.references, self.in_reply_to[0] if self.in_reply_to else "")


@dataclass
class PolicyResult:
    allowed: bool
    reason: str = "ok"
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason, "detail": self.detail}


class CooldownStore(Protocol):
    def is_blocked(self, key: str) -> bool: ...

    def mark(self, key: str, ttl_hours: int) -> None: ...


class MemoryCooldown:
    """进程内冷却表；生产换 Redis（同 key、SETEX）。"""

    def __init__(self, now_fn=None) -> None:
        self._until: dict[str, datetime] = {}
        self._now = now_fn or (lambda: datetime.now(UTC))

    def is_blocked(self, key: str) -> bool:
        until = self._until.get(key)
        if until is None:
            return False
        if until <= self._now():
            self._until.pop(key, None)
            return False
        return True

    def mark(self, key: str, ttl_hours: int) -> None:
        self._until[key] = self._now() + timedelta(hours=ttl_hours)

    def clear(self) -> None:
        self._until.clear()


def cooldown_key(account_id: int, from_addr: str) -> str:
    return f"autoreply:{account_id}:{from_addr.lower()}"


def in_quiet_hours(settings: Settings, now: datetime) -> bool:
    window = settings.quiet_window()
    if window is None:
        return False
    start, end = window
    local = now.astimezone(UTC) + timedelta(hours=settings.quiet_hours_utc_offset)
    minutes = local.hour * 60 + local.minute
    if start == end:
        return False
    if start < end:
        return start <= minutes < end
    # 跨零点，例如 22:00-08:00
    return minutes >= start or minutes < end


class ReplyPolicy:
    def __init__(
        self,
        settings: Settings,
        cooldown: CooldownStore | None = None,
        now_fn=None,
    ) -> None:
        self.settings = settings
        self.cooldown = cooldown or MemoryCooldown(now_fn)
        self._now = now_fn or (lambda: datetime.now(UTC))

    def check(self, ctx: ReplyContext, now: datetime | None = None) -> PolicyResult:
        now = now or self._now()
        s = self.settings

        if not s.auto_reply_enabled:
            return PolicyResult(False, "disabled")
        if ctx.spam_label != "ham":
            return PolicyResult(False, "spam")
        if ctx.category not in s.auto_reply_categories:
            return PolicyResult(False, "category_not_allowed", {"category": ctx.category})
        if is_auto_submitted(ctx.headers):
            return PolicyResult(False, "auto_submitted")
        if is_bulk(ctx.headers):
            return PolicyResult(False, "bulk_or_list")
        # 只有显式空 Return-Path（<>）才是退信；缺失该头是上游 MTA 未补，不算退信
        raw_return_path = ctx.headers.get("return-path")
        if raw_return_path is not None and raw_return_path.strip().strip("<>") == "":
            return PolicyResult(False, "bounce")
        if "mailer-daemon" in ctx.from_addr.lower() or "postmaster" in ctx.from_addr.lower():
            return PolicyResult(False, "bounce")
        local_part = ctx.from_addr.split("@", 1)[0].lower()
        if local_part in {p.lower() for p in s.auto_reply_noreply_localparts}:
            return PolicyResult(False, "noreply_address", {"local_part": local_part})
        if ctx.thread_depth > s.auto_reply_max_thread_depth:
            return PolicyResult(False, "thread_too_deep", {"depth": ctx.thread_depth})
        if ctx.has_risky_attachment:
            return PolicyResult(False, "risky_attachment")
        if in_quiet_hours(s, now):
            return PolicyResult(False, "quiet_hours")
        if self.cooldown.is_blocked(cooldown_key(ctx.account_id, ctx.from_addr)):
            return PolicyResult(False, "rate_limited")
        return PolicyResult(True, "ok")

    def mark_sent(self, account_id: int, from_addr: str) -> None:
        self.cooldown.mark(cooldown_key(account_id, from_addr), self.settings.auto_reply_cooldown_hours)
