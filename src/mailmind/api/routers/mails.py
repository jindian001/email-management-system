"""邮件查询、原文下载、反馈与按需起草。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from mailmind.api.deps import get_mail_service, get_session, require_api_key
from mailmind.api.schemas import FeedbackIn
from mailmind.services.mail_service import MailService

router = APIRouter(prefix="/api/v1/mails", tags=["mails"], dependencies=[Depends(require_api_key)])


@router.get("")
def list_mails(
    account_id: int | None = None,
    status: str | None = None,
    category: str | None = None,
    spam_action: str | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    service: MailService = Depends(get_mail_service),
) -> dict:
    items, total = service.list_mails(
        account_id=account_id,
        status=status,
        category=category,
        spam_action=spam_action,
        q=q,
        page=page,
        size=size,
    )
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/{mail_id}")
def get_mail(mail_id: int, service: MailService = Depends(get_mail_service)) -> dict:
    mail = service.get_mail(mail_id)
    if mail is None:
        raise HTTPException(status_code=404, detail="邮件不存在")
    return mail


@router.get("/{mail_id}/raw")
def get_raw(mail_id: int, service: MailService = Depends(get_mail_service)) -> Response:
    raw = service.raw_mail(mail_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="原始邮件不存在")
    return Response(
        content=raw,
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="mail-{mail_id}.eml"'},
    )


@router.post("/{mail_id}/feedback")
def submit_feedback(
    mail_id: int,
    payload: FeedbackIn,
    service: MailService = Depends(get_mail_service),
) -> dict:
    try:
        return service.submit_feedback(
            mail_id, task=payload.task, label=payload.label, note=payload.note, source=payload.source
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{mail_id}/reply/draft")
def draft_reply(mail_id: int, service: MailService = Depends(get_mail_service)) -> dict:
    """按需重新生成回复草稿（人工点"AI 起草"）。"""
    try:
        return service.generate_draft(mail_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{mail_id}/thread")
def get_thread(mail_id: int, session: Session = Depends(get_session)) -> dict:
    from sqlalchemy import select

    from mailmind.db.models import Mail

    mail = session.get(Mail, mail_id)
    if mail is None:
        raise HTTPException(status_code=404, detail="邮件不存在")
    members = session.scalars(
        select(Mail).where(Mail.thread_id == mail.thread_id).order_by(Mail.received_at)
    ).all()
    return {
        "thread_id": mail.thread_id,
        "count": len(members),
        "mails": [
            {"id": m.id, "from_addr": m.from_addr, "subject": m.subject, "received_at": m.received_at.isoformat() if m.received_at else None}
            for m in members
        ],
    }
