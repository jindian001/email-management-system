"""自动回复护栏（exp.md 4.7.3）。

任何一条硬规则不通过都不允许自动发送；只有 soft issue 时转人工审核。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mailmind.ml.llm import LLMDraft
from mailmind.pipeline.normalize import mask_pii

SENSITIVE_PATTERNS = [
    r"折扣", r"优惠价", r"最低价", r"赔偿", r"合同", r"保证", r"承诺", r"100%",
    r"免费", r"永久", r"discount", r"guarantee", r"refund", r"contract", r"liability",
]
INJECTION_PATTERNS = [
    r"忽略(以上|之前|上面)(的)?(所有)?指令",
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"system\s+prompt",
    r"你现在是",
    r"you\s+are\s+now\s+",
    r"开发者模式",
    r"jailbreak",
]


@dataclass
class GuardrailResult:
    action: str  # send | review | reject
    issues: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.action != "reject"


def detect_injection(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [p for p in INJECTION_PATTERNS if re.search(p, lowered, re.I)]


def check_reply(
    draft: LLMDraft,
    *,
    source_subject: str,
    source_body: str,
    valid_chunk_ids: set[int],
    min_body_length: int = 20,
    max_body_length: int = 2000,
) -> GuardrailResult:
    issues: list[str] = []
    flags: list[str] = []

    body = (draft.body or "").strip()

    # 硬规则：不接受空回复与无依据回复
    if not body:
        return GuardrailResult("reject", ["empty_body"], flags)
    if len(body) < min_body_length:
        return GuardrailResult("reject", ["too_short"], flags)

    citations = [int(c) for c in draft.citations]
    if not citations:
        return GuardrailResult("reject", ["no_citation"], flags)
    if valid_chunk_ids and not set(citations) & valid_chunk_ids:
        return GuardrailResult("reject", ["invalid_citation"], flags)

    # 敏感承诺 → 人工
    if any(re.search(p, body, re.I) for p in SENSITIVE_PATTERNS):
        issues.append("sensitive_commitment")
        flags.append("sensitive_commitment")

    # PII 泄露 → 硬拒绝
    _masked, findings = mask_pii(body)
    leaked = [f["kind"] for f in findings if f["kind"] in {"id_card", "bank_card", "phone_cn"}]
    if leaked:
        return GuardrailResult("reject", [f"pii_leak:{k}" for k in leaked], flags)

    # 正文里出现邮箱以外的异常信息（例如把内部工单号发出去）留给人工
    if len(body) > max_body_length:
        issues.append("too_long")
        flags.append("too_long")

    # 来信本身含注入指令 → 不自动发送
    if detect_injection(source_subject) or detect_injection(source_body):
        issues.append("prompt_injection")
        flags.append("prompt_injection")

    if draft.risk_flags:
        flags.extend(draft.risk_flags)
        issues.append("model_flag")

    if issues:
        return GuardrailResult("review", sorted(set(issues)), sorted(set(flags)))
    return GuardrailResult("send", [], [])
