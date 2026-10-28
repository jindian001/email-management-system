"""知识库：切分、embedding、检索（exp.md 4.7.2）。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from mailmind.core.config import Settings
from mailmind.db.models import KnowledgeDocument
from mailmind.reply.retrieval import HybridRetriever, RetrievedChunk


def chunk_text(content: str, size: int = 512, overlap: int = 80) -> list[str]:
    """按段落切分，尽量不切断语义；超长段落按窗口滑动。"""
    content = (content or "").strip()
    if not content:
        return []
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buffer: list[str] = []
    length = 0

    def flush() -> None:
        nonlocal buffer, length
        if buffer:
            chunks.append("\n\n".join(buffer).strip())
            buffer, length = [], 0

    for para in paragraphs:
        if len(para) > size:
            flush()
            step = max(size - overlap, 1)
            for start in range(0, len(para), step):
                window = para[start : start + size].strip()
                if window:
                    chunks.append(window)
            continue
        if length + len(para) > size:
            flush()
        buffer.append(para)
        length += len(para) + 2
    flush()
    return chunks or [content[:size]]


@dataclass
class KnowledgeHit:
    id: int
    title: str
    content: str
    score: float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "score": round(self.score, 4),
        }


class KnowledgeService:
    def __init__(self, settings: Settings, session: Session, retriever: HybridRetriever | None = None) -> None:
        self.settings = settings
        self.session = session
        self.retriever = retriever or HybridRetriever(settings, session=session)

    def add_document(
        self,
        title: str,
        content: str,
        *,
        source: str = "faq",
        metadata: dict | None = None,
    ) -> list[int]:
        chunks = chunk_text(content, self.settings.chunk_size, self.settings.chunk_overlap)
        ids: list[int] = []
        for index, chunk in enumerate(chunks):
            doc = KnowledgeDocument(
                title=f"{title}" + (f" (#{index + 1})" if len(chunks) > 1 else ""),
                content=chunk,
                source=source,
                embedding=self.retriever.embed_document(title, chunk),
                doc_metadata=metadata or {},
            )
            self.session.add(doc)
            self.session.flush()
            ids.append(doc.id)
        self.session.commit()
        return ids

    def search(self, query: str, top_k: int = 10) -> list[RetrievedChunk]:
        return self.retriever.search(query, top_k=top_k, session=self.session)

    def list_documents(self, limit: int = 100, offset: int = 0) -> list[KnowledgeDocument]:
        return list(
            self.session.scalars(
                select(KnowledgeDocument)
                .order_by(KnowledgeDocument.id)
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def delete_document(self, doc_id: int) -> bool:
        doc = self.session.get(KnowledgeDocument, doc_id)
        if doc is None:
            return False
        self.session.delete(doc)
        self.session.commit()
        return True
