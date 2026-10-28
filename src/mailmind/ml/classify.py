"""邮件自动分类（exp.md 4.6）。

三层：规则（category 种类）→ 分类模型 → 低置信度 LLM few-shot。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from mailmind.core.config import Settings
from mailmind.ml.rules import RuleSet
from mailmind.pipeline.features import FeatureBundle


class ClassifyModel(Protocol):
    version: str

    def predict_proba(self, text: str) -> dict[str, float]: ...

    def top_tokens(self, text: str, label: str, k: int = 5) -> list[tuple[str, float]]: ...


@dataclass
class ClassificationDecision:
    category: str
    scores: dict[str, float] = field(default_factory=dict)
    reason: dict[str, Any] = field(default_factory=dict)
    model_version: str = ""
    used_llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "scores": self.scores,
            "reason": self.reason,
            "model_version": self.model_version,
            "used_llm": self.used_llm,
        }


class EmailClassifier:
    def __init__(
        self,
        settings: Settings,
        rule_set: RuleSet | None = None,
        model: ClassifyModel | None = None,
        llm: Any | None = None,
    ) -> None:
        self.settings = settings
        self.rule_set = rule_set or RuleSet([])
        self.model = model
        self.llm = llm
        self.categories = list(settings.categories)

    def classify(self, features: FeatureBundle, is_spam: bool = False) -> ClassificationDecision:
        reasons: list[dict[str, Any]] = []

        # 0) 垃圾邮件不参与业务分类
        if is_spam:
            return ClassificationDecision(
                "spam",
                {"spam": 1.0},
                {"type": "spam_shortcut", "desc": "已被判定为垃圾邮件"},
                "spam-shortcut",
                False,
            )

        # 1) 规则优先
        hits = [h for h in self.rule_set.evaluate(features) if h.kind == "category"]
        for hit in hits:
            category = (hit.detail or {}).get("category", "other")
            if category in self.categories:
                return ClassificationDecision(
                    category,
                    {category: 0.95},
                    {"type": "rule", "rule_id": hit.rule_id, "desc": hit.description, "detail": hit.detail},
                    "rule",
                    False,
                )

        # 2) 模型
        scores: dict[str, float] = {}
        version = "none"
        if self.model is not None:
            version = getattr(self.model, "version", "model")
            proba = self.model.predict_proba(f"{features.subject}\n{features.text}")
            scores = {cat: round(float(proba.get(cat, 0.0)), 4) for cat in self.categories}
            top = max(scores, key=scores.get)  # type: ignore[arg-type]
            conf = scores[top]
            if conf >= self.settings.classifier_review_threshold:
                return ClassificationDecision(
                    top,
                    scores,
                    {"type": "model", "model": version, "confidence": conf},
                    version,
                    False,
                )
            reasons.append({"type": "model", "model": version, "confidence": conf, "desc": "置信度不足"})
        else:
            top, conf = "other", 0.0

        # 3) LLM 兜底（低置信度 / 无模型）
        if self.llm is not None:
            category, llm_conf = self.llm.classify(
                subject=features.subject, body=features.text[:2000], categories=self.categories
            )
            if category in self.categories and llm_conf >= 0.5:
                scores[category] = max(scores.get(category, 0.0), round(llm_conf, 4))
                return ClassificationDecision(
                    category,
                    scores or {category: llm_conf},
                    {"type": "llm", "candidates": reasons, "confidence": llm_conf},
                    f"{version}+llm",
                    True,
                )

        return ClassificationDecision(
            top if top in self.categories else "other",
            scores or {top: conf},
            {"type": "fallback", "candidates": reasons},
            version,
            self.llm is not None,
        )
