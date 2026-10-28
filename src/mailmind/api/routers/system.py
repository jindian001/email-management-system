"""健康检查、指标、模型重训。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from mailmind import __version__
from mailmind.api.deps import get_app_settings, get_mail_service, get_session, require_api_key
from mailmind.services.mail_service import MailService

router = APIRouter(tags=["system"])


@router.get("/api/v1/health")
def health(
    session: Session = Depends(get_session),
    settings=Depends(get_app_settings),
) -> dict:
    db_ok = True
    try:
        session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "version": __version__,
        "env": settings.env,
        "database": "ok" if db_ok else "error",
        "llm_provider": settings.llm_provider,
        "auto_reply_mode": settings.auto_reply_send_mode,
        "storage": settings.storage_backend,
        "auth": "enabled" if settings.api_key else "disabled",
    }


@router.get("/api/v1/metrics/overview", dependencies=[Depends(require_api_key)])
def overview(service: MailService = Depends(get_mail_service)) -> dict:
    return service.overview()
