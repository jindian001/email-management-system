"""API 限流（固定窗口）。

单机用内存计数；多实例部署可把 ``_state`` 换成 Redis INCR + EXPIRE，
接口保持不变（``hit`` 返回是否放行）。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    limit: int
    window_seconds: float = 60.0
    now_fn: Callable[[], float] = time.monotonic
    _state: dict[str, tuple[float, int]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("limit 必须为正数")

    def hit(self, key: str) -> bool:
        """记一次访问；返回 True 表示放行，False 表示超限。"""
        now = self.now_fn()
        with self._lock:
            start, count = self._state.get(key, (now, 0))
            if now - start >= self.window_seconds:
                start, count = now, 0
            count += 1
            self._state[key] = (start, count)
            if len(self._state) > 10_000:  # 兜底清理，避免长时间运行内存膨胀
                self._state = {
                    k: v for k, v in self._state.items() if now - v[0] < self.window_seconds
                }
            return count <= self.limit

    def reset(self) -> None:
        with self._lock:
            self._state.clear()
