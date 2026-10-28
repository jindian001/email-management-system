"""垃圾邮件级联判定（exp.md 4.5.1）。

顺序：白名单 → 强规则（黑名单/认证/信誉）→ L1 模型 + 启发式 → 模糊区 LLM 复核 → 三档动作。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from mailmind.core.config import Settings
from mailmind.ml.rules import RuleSet
from mailmind.pipeline.features import FeatureBundle


class SpamModel(Protocol):
    version: str

    def predict_proba(self, text: str) -> dict[str, float]: ...

    def top_tokens(self, text: str, label: str, k: int = 5) -> list[tuple[str, float]]: ...


@dataclass
class SpamDecision:
    label: str  # ham | spam | phishing
    score: float
    action: str  # pass | tag | quarantine
    reasons: list[dict[str, Any]] = field(default_factory=list)
    model_version: str = ""
    used_llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "score": self.score,
            "action": self.action,
            "reasons": self.reasons,
            "model_version": self.model_version,
            "used_llm": self.used_llm,
        }


def _clamp(value: float, low: float = 0.0, high: float = 0.99) -> float:
    return max(low, min(high, value))


def heuristic_score(f: FeatureBundle) -> float:
    """无模型时的兜底打分。权重刻意保守，宁可漏也不误杀。"""
    score = 0.0
    if f.urgency_hits >= 2:
        score += 0.22
    elif f.urgency_hits == 1:
        score += 0.08
    if f.ip_urls:
        score += 0.25
    if f.shortener_urls:
        score += 0.12
    if f.punycode_urls:
        score += 0.15
    if f.risky_attachments:
        score += 0.28
    if f.suspicious_display_name:
        score += 0.15
    if f.reply_to_mismatch:
        score += 0.12
    if f.auth_failures >= 2:
        score += 0.30
    elif f.auth_failures == 1:
        score += 0.15
    if f.missing_received:
        score += 0.10
    if f.date_in_future:
        score += 0.15
    if f.caps_ratio > 0.4 and f.text_length > 80:
        score += 0.10
    if f.html_only and f.text_length < 120:
        score += 0.12
    if f.currency_hits >= 3:
        score += 0.10
    # 负向信号：回复线程、老联系人
    if f.is_reply:
        score -= 0.25
    if f.sender_seen and f.sender_spam_ratio < 0.05:
        score -= 0.20
    if f.sender_seen >= 3 and f.sender_spam_ratio > 0.8:
        score += 0.30
    return _clamp(score)


class SpamFilter:
    def __init__(
        self,
        settings: Settings,
        rule_set: RuleSet | None = None,
        model: SpamModel | None = None,
        llm: Any | None = None,
    ) -> None:
        self.settings = settings
        self.rule_set = rule_set or RuleSet([])
        self.model = model
        self.llm = llm

    # ------------------------------------------------------------ 主入口
    def evaluate(self, features: FeatureBundle) -> SpamDecision:
        hits = self.rule_set.evaluate(features)
        reasons: list[dict[str, Any]] = [h.to_reason() for h in hits]

        # 1) 白名单优先级最高
        if any(h.action == "ham" for h in hits):
            return SpamDecision("ham", 0.01, "pass", reasons, self._version(), False)

        # 2) 强规则直接判死
        strong = [
            h
            for h in hits
            if h.action == "spam"
            and h.kind in {"blocklist", "auth", "sender_reputation", "subject_regex"}
        ]
        if strong:
            label = "phishing" if self._looks_phishing(features) else "spam"
            return SpamDecision(
                label, self.settings.spam_rule_hit_score, "quarantine", reasons, self._version(), False
            )

        # 3) 模型 + 启发式
        model_score, model_reason = self._model_score(features)
        if model_reason:
            reasons.append(model_reason)
        base = max(model_score, heuristic_score(features))

        keyword_spam = [h for h in hits if h.action == "spam"]
        if keyword_spam:
            base = max(base, 0.85)
        if any(h.action == "tag" for h in hits):
            base = max(base, self.settings.spam_pass_threshold + 0.01)

        used_llm = False
        # 4) 模糊区交 LLM 复核
        if (
            self.llm is not None
            and self.settings.spam_review_low <= base <= self.settings.spam_review_high
        ):
            review = self.llm.review_spam(
                subject=features.subject,
                body=features.text[:2000],
                signals={
                    "ip_urls": features.ip_urls,
                    "shortener_urls": features.shortener_urls,
                    "risky_attachments": features.risky_attachments,
                    "auth_failures": features.auth_failures,
                    "is_reply": features.is_reply,
                },
            )
            llm_prob = review.spam_probability
            if llm_prob is None:
                llm_prob = review.confidence if review.is_spam else 1.0 - review.confidence
            base = _clamp(0.5 * base + 0.5 * llm_prob)
            used_llm = True
            reasons.append(
                {
                    "type": "llm",
                    "model": getattr(self.llm, "name", "llm"),
                    "is_spam": review.is_spam,
                    "confidence": round(review.confidence, 4),
                    "desc": review.reason or "LLM 复核",
                }
            )

        return self._decide(base, features, reasons, used_llm)

    # ------------------------------------------------------------ 内部
    def _decide(
        self,
        score: float,
        features: FeatureBundle,
        reasons: list[dict[str, Any]],
        used_llm: bool,
    ) -> SpamDecision:
        score = round(_clamp(score), 4)
        if score >= self.settings.spam_quarantine_threshold:
            label = "phishing" if self._looks_phishing(features) else "spam"
            return SpamDecision(label, score, "quarantine", reasons, self._version(), used_llm)
        if score >= self.settings.spam_pass_threshold:
            return SpamDecision("spam", score, "tag", reasons, self._version(), used_llm)
        return SpamDecision("ham", score, "pass", reasons, self._version(), used_llm)

    def _model_score(self, features: FeatureBundle) -> tuple[float, dict[str, Any] | None]:
        if self.model is None:
            return 0.0, None
        text = f"{features.subject}\n{features.text}"
        proba = self.model.predict_proba(text)
        spam = float(proba.get("spam", 0.0))
        tokens = []
        try:
            tokens = [t for t, _ in self.model.top_tokens(text, "spam", 5)]
        except Exception:  # noqa: BLE001 - 解释失败不影响判定
            tokens = []
        return spam, {
            "type": "model",
            "model": self._version(),
            "spam_prob": round(spam, 4),
            "top_tokens": tokens,
            "desc": "TF-IDF/朴素贝叶斯",
        }

    def _looks_phishing(self, f: FeatureBundle) -> bool:
        return bool(f.ip_urls or f.punycode_urls or f.auth_failures or f.suspicious_display_name)

    def _version(self) -> str:
        return getattr(self.model, "version", "heuristic-v1") if self.model else "heuristic-v1"
