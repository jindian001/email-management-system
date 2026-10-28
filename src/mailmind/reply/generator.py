"""自动回复生成：检索 → 生成 → 护栏 → 决定状态（exp.md 4.7.2）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from mailmind.core.config import Settings
from mailmind.ml.guardrails import GuardrailResult, check_reply
from mailmind.ml.llm import LLMDraft, LLMGateway, detect_language
from mailmind.reply.retrieval import HybridRetriever, RetrievedChunk, query_from_mail, rerank


@dataclass
class GenerationResult:
    draft: LLMDraft
    chunks: list[RetrievedChunk] = field(default_factory=list)
    guardrail: GuardrailResult = field(default_factory=lambda: GuardrailResult("reject", ["no_draft"]))
    confidence: float = 0.0
    status: str = "rejected"  # send | pending_review | rejected

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "confidence": self.confidence,
            "intent": self.draft.intent,
            "subject": self.draft.subject,
            "body": self.draft.body,
            "citations": self.draft.citations,
            "risk_flags": self.guardrail.risk_flags,
            "issues": self.guardrail.issues,
            "chunks": [c.to_dict() for c in self.chunks],
        }


class ReplyGenerator:
    def __init__(
        self,
        settings: Settings,
        llm: LLMGateway,
        retriever: HybridRetriever,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.retriever = retriever

    def generate(
        self,
        *,
        subject: str,
        body: str,
        session: Session | None = None,
        language: str | None = None,
    ) -> GenerationResult:
        query = query_from_mail(subject, body)
        candidates = self.retriever.search(query, session=session)
        chunks = rerank(query, candidates, keep=self.settings.retrieval_rerank_k)
        chunks = [c for c in chunks if c.score >= self.settings.retrieval_min_score]

        draft = self.llm.draft_reply(
            subject=subject,
            body=body,
            chunks=[c.to_dict() for c in chunks],
            language=language or detect_language(body),
        )

        guardrail = check_reply(
            draft,
            source_subject=subject,
            source_body=body,
            valid_chunk_ids={c.id for c in chunks},
        )

        top_score = chunks[0].score if chunks else 0.0
        confidence = round(min(draft.confidence, 0.5 + top_score * 0.5), 4) if chunks else 0.0

        status = self._decide_status(guardrail, confidence)
        return GenerationResult(
            draft=draft,
            chunks=chunks,
            guardrail=guardrail,
            confidence=confidence,
            status=status,
        )

    def _decide_status(self, guardrail: GuardrailResult, confidence: float) -> str:
        s = self.settings
        if guardrail.action == "reject":
            return "rejected"
        if guardrail.action == "review":
            return "pending_review"
        if confidence < s.auto_reply_review_min_confidence:
            return "rejected"
        if s.auto_reply_send_mode == "review":
            return "pending_review"
        if confidence >= s.auto_reply_min_confidence:
            return "send"
        return "pending_review"
