"""运营与运维接口：规则试算、模型重训、审计、反馈查询。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from mailmind.api.deps import (
    get_app_settings,
    get_mail_service,
    get_runtime,
    get_session,
    require_api_key,
)
from mailmind.api.schemas import RuleTestIn
from mailmind.services.mail_service import MailService
from mailmind.services.runtime import Runtime
from mailmind.services.training import rebuild_from_db

router = APIRouter(tags=["admin"], dependencies=[Depends(require_api_key)])


@router.post("/api/v1/rules/test")
def test_rules(payload: RuleTestIn, service: MailService = Depends(get_mail_service)) -> dict:
    """规则命中测试器：输入一封邮件，返回判定、命中规则与原因（不落库）。"""
    return service.test_rules(
        raw=payload.raw,
        subject=payload.subject,
        from_addr=payload.from_addr,
        body=payload.body,
    )


@router.post("/api/v1/admin/retrain")
def retrain(
    session: Session = Depends(get_session),
    settings=Depends(get_app_settings),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    """用反馈数据立即重训，并热替换运行时模型（exp.md 4.8）。"""
    stats = rebuild_from_db(session, settings)
    from mailmind.services.training import load_category_model, load_spam_model

    runtime.spam_model = load_spam_model(settings)
    runtime.category_model = load_category_model(settings)
    return {
        "ok": True,
        "stats": stats,
        "models": {
            "spam": getattr(runtime.spam_model, "version", None),
            "category": getattr(runtime.category_model, "version", None),
        },
    }


@router.get("/api/v1/audit")
def list_audit(
    action: str | None = Query(default=None, description="按动作前缀过滤，如 mail./reply./quarantine."),
    limit: int = Query(default=100, ge=1, le=500),
    service: MailService = Depends(get_mail_service),
) -> dict:
    return {"items": service.list_audit(limit=limit, action=action)}


@router.get("/api/v1/feedback")
def list_feedback(
    mail_id: int | None = None,
    task: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    service: MailService = Depends(get_mail_service),
) -> dict:
    return {"items": service.list_feedback(mail_id=mail_id, task=task, limit=limit)}
