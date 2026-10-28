"""账号管理与同步。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from mailmind.api.deps import get_app_settings, get_runtime, get_session, require_api_key
from mailmind.api.schemas import AccountIn, AccountOut, IngestIn, IngestOut, SyncOut
from mailmind.connectors.factory import build_connector
from mailmind.core.config import Settings
from mailmind.core.security import secret_box
from mailmind.db.models import Account
from mailmind.services.ingest import IngestService
from mailmind.services.runtime import Runtime

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"], dependencies=[Depends(require_api_key)])


@router.post("", response_model=AccountOut, status_code=201)
def create_account(
    payload: AccountIn,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> Account:
    if session.scalar(select(Account).where(Account.email == payload.email)) is not None:
        raise HTTPException(status_code=409, detail="账号已存在")
    account = Account(
        email=payload.email,
        provider=payload.provider,
        display_name=payload.display_name,
        config=payload.config,
        secret_enc=secret_box(settings).encrypt(payload.secret) if payload.secret else "",
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


@router.get("", response_model=list[AccountOut])
def list_accounts(session: Session = Depends(get_session)) -> list[Account]:
    return list(session.scalars(select(Account).order_by(Account.id)).all())


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: int, session: Session = Depends(get_session)) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    return account


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, session: Session = Depends(get_session)) -> None:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    session.delete(account)
    session.commit()


@router.post("/{account_id}/ingest", response_model=IngestOut)
def ingest_raw(
    account_id: int,
    payload: IngestIn,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    runtime: Runtime = Depends(get_runtime),
) -> IngestOut:
    """直接投递一封原始邮件（联调、回放、迁移都走这里）。"""
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    try:
        if payload.base64:
            import base64

            raw = base64.b64decode(payload.raw)
        else:
            raw = payload.raw.encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"raw 编码错误: {exc}") from exc

    outcome = IngestService(settings, session, runtime).ingest_raw(
        account, raw, folder=payload.folder, uid=payload.uid
    )
    if outcome.status == "error":
        raise HTTPException(status_code=422, detail=outcome.error or "解析失败")
    return IngestOut(
        status=outcome.status,
        mail_id=outcome.mail_id,
        message_id=outcome.message_id,
        error=outcome.error,
        reply_status=outcome.reply_status,
    )


@router.post("/{account_id}/sync", response_model=SyncOut)
def sync_account(
    account_id: int,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    runtime: Runtime = Depends(get_runtime),
) -> SyncOut:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    connector = request.app.state.connectors.get(account_id) or build_connector(account, settings)
    if connector is None:
        raise HTTPException(
            status_code=400, detail="该账号未配置可用的连接器（provider=memory 时需先注入 MemoryConnector）"
        )
    result = IngestService(settings, session, runtime).sync_account(account, connector, limit)
    return SyncOut(**result.to_dict())
