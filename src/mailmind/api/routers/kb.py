"""知识库：导入、检索、删除。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mailmind.api.deps import get_app_settings, get_runtime, get_session, require_api_key
from mailmind.api.schemas import KbIn
from mailmind.services.kb import KnowledgeService
from mailmind.services.runtime import Runtime

router = APIRouter(prefix="/api/v1/kb", tags=["knowledge"], dependencies=[Depends(require_api_key)])


def _service(session: Session, settings, runtime: Runtime) -> KnowledgeService:
    return KnowledgeService(settings, session, runtime.retriever(session))


@router.get("/documents")
def list_documents(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    settings=Depends(get_app_settings),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    docs = _service(session, settings, runtime).list_documents(limit=limit, offset=offset)
    return {
        "items": [
            {
                "id": d.id,
                "title": d.title,
                "content": d.content,
                "source": d.source,
                "metadata": d.doc_metadata,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }
            for d in docs
        ]
    }


@router.post("/documents", status_code=201)
def add_document(
    payload: KbIn,
    session: Session = Depends(get_session),
    settings=Depends(get_app_settings),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    ids = _service(session, settings, runtime).add_document(
        payload.title, payload.content, source=payload.source, metadata=payload.metadata
    )
    return {"ids": ids, "chunks": len(ids)}


@router.get("/search")
def search(
    q: str = Query(min_length=1),
    top_k: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
    settings=Depends(get_app_settings),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    hits = _service(session, settings, runtime).search(q, top_k=top_k)
    return {"items": [h.to_dict() for h in hits]}


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(
    doc_id: int,
    session: Session = Depends(get_session),
    settings=Depends(get_app_settings),
    runtime: Runtime = Depends(get_runtime),
) -> None:
    if not _service(session, settings, runtime).delete_document(doc_id):
        raise HTTPException(status_code=404, detail="文档不存在")
