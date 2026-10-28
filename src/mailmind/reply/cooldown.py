"""自动回复冷却存储。

生产用 Redis（多进程共享），测试/单机用内存实现；两者语义一致：
``is_blocked`` 只读，``mark`` 才写入，避免"检查通过但最终未发送"也占用冷却名额。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

log = logging.getLogger(__name__)


class CooldownStore(Protocol):
    def is_blocked(self, key: str) -> bool: ...

    def mark(self, key: str, ttl_hours: int) -> None: ...


def cooldown_key(account_id: int, from_addr: str) -> str:
    return f"autoreply:{account_id}:{from_addr.lower()}"


class MemoryCooldown:
    """进程内冷却表。"""

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


class RedisCooldown:
    """Redis 实现：SET NX EX（多实例共享，重启不丢）。"""

    def __init__(self, client: Any, prefix: str = "mailmind:cooldown") -> None:
        self.client = client
        self.prefix = prefix

    def _name(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    def is_blocked(self, key: str) -> bool:
        return bool(self.client.exists(self._name(key)))

    def mark(self, key: str, ttl_hours: int) -> None:
        self.client.set(self._name(key), "1", ex=max(int(ttl_hours), 1) * 3600)


def build_cooldown(settings, client: Any | None = None) -> CooldownStore:
    """默认内存；显式配置 redis 且能 ping 通才用 Redis，否则降级并告警。"""
    if getattr(settings, "cooldown_backend", "memory") != "redis":
        return MemoryCooldown()
    try:
        if client is None:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
            client.ping()
        return RedisCooldown(client)
    except Exception as exc:  # noqa: BLE001 - 降级不阻塞主流程
        log.warning("redis cooldown 不可用，降级为内存实现: %s", exc)
        return MemoryCooldown()
