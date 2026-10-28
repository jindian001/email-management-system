"""自动回复草稿：审核、通过发送、拒绝。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mailmind.api.deps import get_mail_service, get_session, require_api_key
from mailmind.api.schemas import ApproveIn, RejectIn
from mailmind.db.models import ReplyDraft
from mailmind.services.mail_service import MailService, serialize_draft

router = APIRouter(prefix="/api/v1/replies", tags=["replies"], dependencies=[Depends(require_api_key)])


@router.get("")
def list_drafts(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    service: MailService = Depends(get_mail_service),
) -> dict:
    items = service.list_drafts(status=status, page=page, size=size)
    return {"items": items, "page": page, "size": size}


@router.get("/{draft_id}")
def get_draft(draft_id: int, session: Session = Depends(get_session)) -> dict:
    draft = session.get(ReplyDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    return serialize_draft(draft)


@router.post("/{draft_id}/approve")
def approve(
    draft_id: int,
    payload: ApproveIn,
    service: MailService = Depends(get_mail_service),
) -> dict:
    try:
        return service.approve_draft(
            draft_id, reviewer_id=payload.reviewer_id, body=payload.body, actor=f"user:{payload.reviewer_id}"
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{draft_id}/reject")
def reject(
    draft_id: int,
    payload: RejectIn,
    service: MailService = Depends(get_mail_service),
) -> dict:
    try:
        return service.reject_draft(draft_id, reviewer_id=payload.reviewer_id, reason=payload.reason)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
