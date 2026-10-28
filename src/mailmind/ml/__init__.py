from __future__ import annotations

from mailmind.ml.classify import ClassificationDecision, EmailClassifier
from mailmind.ml.embeddings import Embedder, HashingEmbedder, cosine
from mailmind.ml.guardrails import GuardrailResult, check_reply, detect_injection
from mailmind.ml.llm import (
    INTENTS,
    FallbackGateway,
    LLMDraft,
    LLMError,
    LLMGateway,
    OpenAICompatGateway,
    SpamReview,
    TemplateGateway,
    build_gateway,
    detect_language,
    infer_intent,
)
from mailmind.ml.naive_bayes import NaiveBayesModel
from mailmind.ml.rules import Rule, RuleHit, RuleSet
from mailmind.ml.spam import SpamDecision, SpamFilter, heuristic_score
from mailmind.ml.text import keyword_hits, token_set, tokenize

__all__ = [
    "INTENTS",
    "ClassificationDecision",
    "EmailClassifier",
    "Embedder",
    "FallbackGateway",
    "GuardrailResult",
    "HashingEmbedder",
    "LLMDraft",
    "LLMError",
    "LLMGateway",
    "NaiveBayesModel",
    "OpenAICompatGateway",
    "Rule",
    "RuleHit",
    "RuleSet",
    "SpamDecision",
    "SpamFilter",
    "SpamReview",
    "TemplateGateway",
    "build_gateway",
    "check_reply",
    "cosine",
    "detect_injection",
    "detect_language",
    "heuristic_score",
    "infer_intent",
    "keyword_hits",
    "token_set",
    "tokenize",
]
