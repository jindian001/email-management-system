"""结构化日志与 trace_id。

日志统一输出 JSON，方便 ELK/Loki 采集；每个请求/任务携带同一个 trace_id。
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

import structlog

_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_configured = False


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def get_trace_id() -> str:
    tid = _trace_id.get()
    if not tid:
        tid = new_trace_id()
        _trace_id.set(tid)
    return tid


def set_trace_id(tid: str) -> None:
    _trace_id.set(tid)


def _add_trace_id(_logger, _method, event_dict):  # pragma: no cover - 结构固定
    event_dict.setdefault("trace_id", _trace_id.get(""))
    return event_dict


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    global _configured
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    processors = [
        structlog.contextvars.merge_contextvars,
        _add_trace_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if json_logs:
        processors.append(structlog.processors.JSONRenderer(ensure_ascii=False))
    else:  # pragma: no cover - 本地开发可读性
        processors.append(structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str = "mailmind"):
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)
