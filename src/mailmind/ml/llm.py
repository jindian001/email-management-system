"""LLM 网关。

设计要点（exp.md 4.7）：
- 上层只依赖 :class:`LLMGateway` 协议，因此可以离线跑 ``TemplateGateway``；
- 真实调用走 OpenAI 兼容协议（DeepSeek / Qwen / vLLM 均可），失败时降级到模板，绝不让主流程挂掉。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from mailmind.core.logging import get_logger

log = get_logger("mailmind.llm")

INTENTS = ["consult", "quote", "aftersale", "booking", "complaint", "other"]

# 意图关键词（模板网关与本地兜底共用）
INTENT_KEYWORDS: dict[str, list[str]] = {
    "quote": ["报价", "价格", "多少钱", "费用", "采购", "quote", "pricing", "price"],
    "aftersale": ["售后", "退货", "维修", "故障", "保修", "refund", "warranty", "repair"],
    "booking": ["预约", "预定", "会议", "上门", "booking", "appointment", "schedule"],
    "complaint": ["投诉", "不满", "差评", "太差", "complaint", "angry", "unacceptable"],
    "consult": ["咨询", "请问", "怎么", "如何", "支持", "inquiry", "question", "help", "how"],
}


class LLMError(RuntimeError):
    pass


@dataclass
class SpamReview:
    is_spam: bool
    confidence: float
    reason: str = ""
    # 统一的"是垃圾邮件的概率"，供级联融合使用（不同网关语义不同，这里强制归一）
    spam_probability: float | None = None

    def __post_init__(self) -> None:
        if self.spam_probability is None:
            self.spam_probability = (
                self.confidence if self.is_spam else 1.0 - self.confidence
            )


@dataclass
class LLMDraft:
    intent: str = "other"
    subject: str = ""
    body: str = ""
    confidence: float = 0.0
    citations: list[int] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    model: str = ""
    cost_usd: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


class LLMGateway(Protocol):
    name: str

    def review_spam(self, *, subject: str, body: str, signals: dict[str, Any]) -> SpamReview: ...

    def classify(self, *, subject: str, body: str, categories: list[str]) -> tuple[str, float]: ...

    def draft_reply(
        self, *, subject: str, body: str, chunks: list[dict[str, Any]], language: str = "zh"
    ) -> LLMDraft: ...


# ---------------------------------------------------------------- 模板网关


def infer_intent(text: str) -> str:
    lowered = (text or "").lower()
    best, best_hits = "other", 0
    for intent, words in INTENT_KEYWORDS.items():
        hits = sum(1 for w in words if w in lowered)
        if hits > best_hits:
            best, best_hits = intent, hits
    return best


def detect_language(text: str) -> str:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    return "zh" if cjk >= latin else "en"


class TemplateGateway:
    """离线确定性网关：不联网、可复现，测试与演示默认使用。"""

    name = "template"

    def __init__(self, app_name: str = "MailMind") -> None:
        self.app_name = app_name

    def review_spam(self, *, subject: str, body: str, signals: dict[str, Any]) -> SpamReview:
        text = f"{subject}\n{body}".lower()
        score = 0.0
        reasons: list[str] = []
        rules = [
            (["中奖", "恭喜您", "立即领取", "限时免费", "congratulations", "you have won"], 0.45, "中奖诱导"),
            (["验证码", "verify your account", "账户异常", "password expired", "账号将被冻结"], 0.25, "账号诱导"),
            (["贷款", "刷单", "返现", "博彩", "博彩", "发票代开"], 0.4, "灰产关键词"),
            (["click here", "unsubscribe", "退订"], 0.15, "营销话术"),
        ]
        for words, weight, label in rules:
            if any(w in text for w in words):
                score += weight
                reasons.append(label)
        if signals.get("ip_urls"):
            score += 0.25
            reasons.append("IP 直连链接")
        if signals.get("shortener_urls"):
            score += 0.15
            reasons.append("短链")
        if signals.get("risky_attachments"):
            score += 0.3
            reasons.append("危险附件")
        if signals.get("auth_failures"):
            score += 0.2
            reasons.append("发件域认证失败")
        if signals.get("is_reply"):
            score -= 0.25
        score = max(0.0, min(score, 0.99))
        return SpamReview(
            is_spam=score >= 0.5,
            confidence=round(score, 4),
            reason="、".join(reasons) or "无异常信号",
            spam_probability=round(score, 4),
        )

    def classify(self, *, subject: str, body: str, categories: list[str]) -> tuple[str, float]:
        text = f"{subject}\n{body}".lower()
        hints = {
            "billing": ["发票", "账单", "付款", "invoice", "payment", "receipt", "报销"],
            "notice": ["通知", "公告", "提醒", "维护", "notification", "announcement"],
            "marketing": ["推广", "促销", "优惠", "订阅", "newsletter", "unsubscribe"],
            "social": ["linkedin", "facebook", "twitter", "关注", "好友"],
            "recruiting": ["简历", "面试", "招聘", "offer", "resume", "interview"],
            "complaint": ["投诉", "不满", "差评", "complaint"],
            "consult": ["咨询", "请问", "报价", "价格", "inquiry", "question"],
        }
        best, hits = "other", 0
        for category, words in hints.items():
            if category not in categories:
                continue
            count = sum(1 for w in words if w in text)
            if count > hits:
                best, hits = category, count
        if hits == 0:
            return "other", 0.0
        return best, round(min(0.55 + 0.1 * hits, 0.8), 4)

    def draft_reply(
        self, *, subject: str, body: str, chunks: list[dict[str, Any]], language: str = "zh"
    ) -> LLMDraft:
        intent = infer_intent(f"{subject}\n{body}")
        if not chunks:
            return LLMDraft(
                intent=intent,
                confidence=0.0,
                risk_flags=["no_grounding"],
                model=self.name,
            )
        top = max(chunks, key=lambda c: float(c.get("score", 0.0)))
        answer = _summarize(top.get("content", ""), 320)
        lang = language or detect_language(body)
        greeting = "您好，" if lang == "zh" else "Hello,"
        closing = (
            "如需进一步协助，请直接回复本邮件。\n\n此致\n{app} 客服团队"
            if lang == "zh"
            else "If you need anything else, just reply to this email.\n\nBest regards,\n{app} Support"
        ).format(app=self.app_name)
        reply_subject = subject if (subject or "").lower().startswith("re:") else f"Re: {subject}"
        confidence = round(min(0.95, 0.55 + float(top.get("score", 0.0)) * 0.4), 4)
        return LLMDraft(
            intent=intent,
            subject=reply_subject,
            body=f"{greeting}\n\n{answer}\n\n{closing}",
            confidence=confidence,
            citations=[int(top["id"])] if top.get("id") is not None else [],
            model=self.name,
        )


def _summarize(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("。", "！", "？", ".", "!", "?"):
        idx = cut.rfind(sep)
        if idx > limit // 2:
            return cut[: idx + 1]
    return cut + "…"


# ---------------------------------------------------------------- OpenAI 兼容网关

_SYSTEM_REPLY = """你是企业客服，负责根据给定知识库片段撰写中文邮件回复。
规则：
- 只能使用【知识片段】中的事实，不得编造；
- 不确定或需要人工确认时，need_human 置为 true；
- 不承诺价格、折扣、交付时间，不涉及法律条款；
- 语言跟随来信语言。
返回 JSON：{"intent": "...", "subject": "...", "body": "...", "confidence": 0.0, "citations": [片段编号], "need_human": false}
"""


class OpenAICompatGateway:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        http_client: Any | None = None,
    ) -> None:
        if http_client is None:
            import httpx

            http_client = httpx.Client(timeout=timeout)
        self.client = http_client
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.name = f"openai:{model}"

    def _chat(self, system: str, user: str) -> dict[str, Any]:
        if not self.api_key:
            raise LLMError("未配置 MAILMIND_LLM_API_KEY")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        try:
            resp = self.client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"LLM 调用失败: {exc}") from exc
        return _parse_json(content)

    def review_spam(self, *, subject: str, body: str, signals: dict[str, Any]) -> SpamReview:
        system = "你是垃圾邮件审核器。只输出 JSON：{\"is_spam\": bool, \"confidence\": 0-1, \"reason\": \"...\"}"
        user = json.dumps(
            {"subject": subject, "body": body[:2000], "signals": signals}, ensure_ascii=False
        )
        data = self._chat(system, user)
        is_spam = bool(data.get("is_spam", False))
        confidence = float(data.get("confidence", 0.5))
        return SpamReview(
            is_spam=is_spam,
            confidence=confidence,
            reason=str(data.get("reason", "")),
            spam_probability=confidence if is_spam else 1.0 - confidence,
        )

    def classify(self, *, subject: str, body: str, categories: list[str]) -> tuple[str, float]:
        system = (
            "你是邮件分类器。类别只能从给定列表中选择。"
            '只输出 JSON：{"category": "...", "confidence": 0-1}'
        )
        user = json.dumps(
            {"categories": categories, "subject": subject, "body": body[:2000]}, ensure_ascii=False
        )
        data = self._chat(system, user)
        category = str(data.get("category", "other"))
        if category not in categories:
            category = "other"
        return category, float(data.get("confidence", 0.0))

    def draft_reply(
        self, *, subject: str, body: str, chunks: list[dict[str, Any]], language: str = "zh"
    ) -> LLMDraft:
        context = "\n\n".join(
            f"[{c['id']}] {c.get('title', '')}\n{c.get('content', '')}" for c in chunks
        )
        user = f"【知识片段】\n{context}\n\n【来信】\n主题：{subject}\n正文：{body[:3000]}"
        data = self._chat(_SYSTEM_REPLY, user)
        need_human = bool(data.get("need_human", False))
        return LLMDraft(
            intent=str(data.get("intent", "other")),
            subject=str(data.get("subject", f"Re: {subject}")),
            body=str(data.get("body", "")),
            confidence=0.0 if need_human else float(data.get("confidence", 0.0)),
            citations=[int(c) for c in data.get("citations", []) if str(c).isdigit()],
            risk_flags=["need_human"] if need_human else [],
            model=self.name,
        )


def _parse_json(content: str) -> dict[str, Any]:
    content = (content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.M).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    raise LLMError(f"无法解析 LLM 返回: {content[:200]}")


class FallbackGateway:
    """真实网关失败时降级到模板，保证自动回复链路不中断。"""

    def __init__(self, primary: LLMGateway, fallback: LLMGateway | None = None) -> None:
        self.primary = primary
        self.fallback = fallback or TemplateGateway()
        self.name = f"{primary.name}+fallback"
        self.last_error: str = ""

    def _call(self, method: str, **kwargs):
        try:
            return getattr(self.primary, method)(**kwargs)
        except LLMError as exc:
            self.last_error = str(exc)
            log.warning("llm_fallback", method=method, error=str(exc))
            return getattr(self.fallback, method)(**kwargs)

    def review_spam(self, **kwargs) -> SpamReview:
        return self._call("review_spam", **kwargs)

    def classify(self, **kwargs) -> tuple[str, float]:
        return self._call("classify", **kwargs)

    def draft_reply(self, **kwargs) -> LLMDraft:
        return self._call("draft_reply", **kwargs)


def build_gateway(settings) -> LLMGateway:
    if settings.llm_provider == "openai" and settings.llm_api_key:
        return FallbackGateway(
            OpenAICompatGateway(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                timeout=settings.llm_timeout_seconds,
            ),
            TemplateGateway(settings.app_name),
        )
    return TemplateGateway(settings.app_name)
