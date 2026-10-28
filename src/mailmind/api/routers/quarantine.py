"""隔离区：放行（可加白名单）与删除。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from mailmind.api.deps import get_mail_service, require_api_key
from mailmind.services.mail_service import MailService

router = APIRouter(
    prefix="/api/v1/quarantine", tags=["quarantine"], dependencies=[Depends(require_api_key)]
)


@router.get("")
def list_quarantine(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    service: MailService = Depends(get_mail_service),
) -> dict:
    items, total = service.list_quarantine(page=page, size=size)
    return {"items": items, "total": total, "page": page, "size": size}


@router.post("/{mail_id}/release")
def release(
    mail_id: int,
    add_allowlist: bool = True,
    service: MailService = Depends(get_mail_service),
) -> dict:
    try:
        return service.release_quarantine(mail_id, add_allowlist=add_allowlist)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{mail_id}/delete")
def delete(mail_id: int, service: MailService = Depends(get_mail_service)) -> dict:
    ok = service.delete_quarantine(mail_id)
    if not ok:
        raise HTTPException(status_code=404, detail="邮件不存在")
    return {"deleted": True, "mail_id": mail_id}
