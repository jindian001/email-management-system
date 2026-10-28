"""API 依赖：会话、运行时、鉴权。"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from mailmind.core.config import Settings
from mailmind.core.security import api_key_ok
from mailmind.services.mail_service import MailService
from mailmind.services.runtime import Runtime


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def require_api_key(
    request: Request, x_api_key: str | None = Header(default=None, alias="X-API-Key")
) -> None:
    settings: Settings = request.app.state.settings
    if not api_key_ok(settings, x_api_key):
        raise HTTPException(status_code=401, detail="无效或缺失的 X-API-Key")


def get_mail_service(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    runtime: Runtime = Depends(get_runtime),
) -> MailService:
    return MailService(settings, session, runtime)
