"""审计日志写入。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from mailmind.core.logging import get_trace_id
from mailmind.db.models import AuditLog


def record(
    session: Session,
    *,
    actor: str,
    action: str,
    target: str,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor=actor,
        action=action,
        target=target,
        detail=detail or {},
        trace_id=get_trace_id(),
    )
    session.add(entry)
    return entry
