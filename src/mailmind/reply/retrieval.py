"""混合检索（BM25 + 向量余弦），exp.md 4.7.2。

知识库规模在万级以内时，纯 Python 完全够用；接口设计成可平滑替换为 pgvector + 重排模型。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from mailmind.core.config import Settings
from mailmind.ml.embeddings import Embedder, HashingEmbedder, cosine
from mailmind.ml.text import tokenize


@dataclass
class RetrievedChunk:
    id: int
    title: str
    content: str
    score: float
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "score": round(self.score, 4),
            "source": self.source,
        }


class BM25Index:
    def __init__(self, docs: Sequence[tuple[int, str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.doc_ids = [doc_id for doc_id, _ in docs]
        self.tokens = [tokenize(text) for _, text in docs]
        self.tfs = [Counter(toks) for toks in self.tokens]
        self.lengths = [len(toks) for toks in self.tokens]
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        self.k1 = k1
        self.b = b
        self.df: Counter[str] = Counter()
        for tf in self.tfs:
            for term in tf:
                self.df[term] += 1
        self.n = len(self.tokens)

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 20) -> list[tuple[int, float]]:
        terms = tokenize(query)
        if not terms or not self.n:
            return []
        scores: list[tuple[int, float]] = []
        for i, tf in enumerate(self.tfs):
            length = self.lengths[i] or 1
            score = 0.0
            for term in terms:
                freq = tf.get(term)
                if not freq:
                    continue
                denom = freq + self.k1 * (1 - self.b + self.b * length / (self.avg_len or 1))
                score += self._idf(term) * freq * (self.k1 + 1) / denom
            if score > 0:
                scores.append((self.doc_ids[i], score))
        scores.sort(key=lambda kv: -kv[1])
        return scores[:top_k]


class HybridRetriever:
    def __init__(
        self,
        settings: Settings,
        embedder: Embedder | None = None,
        session: Session | None = None,
    ) -> None:
        self.settings = settings
        self.embedder = embedder or HashingEmbedder(settings.embedding_dim)
        self.session = session

    # ------------------------------------------------------------ 索引
    def embed_document(self, title: str, content: str) -> list[float]:
        return self.embedder.embed(f"{title}\n{content}")

    # ------------------------------------------------------------ 检索
    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        documents: list[dict] | None = None,
        session: Session | None = None,
    ) -> list[RetrievedChunk]:
        top_k = top_k or self.settings.retrieval_top_k
        docs = documents if documents is not None else self._load(session or self.session)
        if not docs:
            return []

        bm25 = BM25Index([(d["id"], f"{d.get('title', '')}\n{d.get('content', '')}") for d in docs])
        bm25_scores = dict(bm25.search(query, top_k=top_k))
        max_bm25 = max(bm25_scores.values(), default=0.0) or 1.0

        query_vec = self.embedder.embed(query)
        ranked: list[RetrievedChunk] = []
        for doc in docs:
            bm25_norm = bm25_scores.get(doc["id"], 0.0) / max_bm25
            vec = doc.get("embedding") or []
            cos = max(0.0, cosine(query_vec, vec)) if vec else 0.0
            hybrid = 0.5 * bm25_norm + 0.5 * cos
            if hybrid > 0:
                ranked.append(
                    RetrievedChunk(
                        id=int(doc["id"]),
                        title=doc.get("title", ""),
                        content=doc.get("content", ""),
                        score=hybrid,
                        source=doc.get("source", ""),
                    )
                )
        ranked.sort(key=lambda c: -c.score)
        return [c for c in ranked[:top_k] if c.score >= self.settings.retrieval_min_score]

    def _load(self, session: Session | None) -> list[dict]:
        if session is None:
            return []
        from mailmind.db.models import KnowledgeDocument

        rows = session.scalars(select(KnowledgeDocument)).all()
        return [
            {
                "id": row.id,
                "title": row.title,
                "content": row.content,
                "source": row.source,
                "embedding": row.embedding or [],
            }
            for row in rows
        ]


def rerank(query: str, chunks: list[RetrievedChunk], keep: int = 5) -> list[RetrievedChunk]:
    """轻量重排：用查询词覆盖率加权（生产替换为 bge-reranker）。"""
    if not chunks:
        return []
    terms = set(tokenize(query))
    rescored: list[RetrievedChunk] = []
    for chunk in chunks:
        doc_terms = set(tokenize(f"{chunk.title} {chunk.content}"))
        coverage = len(terms & doc_terms) / len(terms) if terms else 0.0
        combined = 0.7 * chunk.score + 0.3 * coverage
        rescored.append(
            RetrievedChunk(
                id=chunk.id,
                title=chunk.title,
                content=chunk.content,
                score=round(combined, 4),
                source=chunk.source,
            )
        )
    rescored.sort(key=lambda c: -c.score)
    return rescored[:keep]


def query_from_mail(subject: str, body: str, limit: int = 1200) -> str:
    text = f"{subject}\n{body}"
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]
