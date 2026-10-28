"""规则引擎（exp.md 4.5.1 的 L0 层）。

规则存在数据库里，可热更新；此处只做"特征 → 命中列表"的纯计算，便于单测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mailmind.pipeline.features import FeatureBundle

KINDS = {
    "allowlist",
    "blocklist",
    "keyword",
    "header",
    "auth",
    "sender_reputation",
    "category",
    "subject_regex",
}


@dataclass
class Rule:
    kind: str
    action: str = "spam"
    payload: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    scope: str = "global"
    scope_id: str = ""
    priority: int = 100
    enabled: bool = True
    description: str = ""


@dataclass
class RuleHit:
    rule_id: int | None
    kind: str
    action: str
    description: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_reason(self) -> dict[str, Any]:
        return {
            "type": "rule",
            "rule_id": self.rule_id,
            "kind": self.kind,
            "action": self.action,
            "desc": self.description or self.kind,
            "detail": self.detail,
        }


def _domain_match(domain: str, patterns: list[str]) -> str | None:
    domain = (domain or "").lower()
    if not domain:
        return None
    for pattern in patterns:
        p = pattern.lower().strip().lstrip("@")
        if not p:
            continue
        if domain == p or domain.endswith("." + p):
            return pattern
    return None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


class RuleSet:
    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules = sorted(
            [r for r in (rules or []) if r.enabled],
            key=lambda r: (r.priority, r.id or 0),
        )

    @classmethod
    def from_db(cls, session: Session, account_id: int | None = None) -> RuleSet:
        from mailmind.db.models import Rule as RuleModel

        rows = session.scalars(select(RuleModel).where(RuleModel.enabled.is_(True))).all()
        rules: list[Rule] = []
        for row in rows:
            if row.scope == "account" and account_id is not None:
                if str(row.scope_id) != str(account_id):
                    continue
            rules.append(
                Rule(
                    id=row.id,
                    kind=row.kind,
                    action=row.action,
                    payload=dict(row.payload or {}),
                    scope=row.scope,
                    scope_id=row.scope_id,
                    priority=row.priority,
                    enabled=row.enabled,
                    description=row.description,
                )
            )
        return cls(rules)

    # ------------------------------------------------------------ 求值
    def evaluate(self, features: FeatureBundle) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for rule in self.rules:
            detail = self._match(rule, features)
            if detail is not None:
                hits.append(
                    RuleHit(
                        rule_id=rule.id,
                        kind=rule.kind,
                        action=rule.action,
                        description=rule.description,
                        detail=detail,
                    )
                )
        return hits

    def _match(self, rule: Rule, f: FeatureBundle) -> dict[str, Any] | None:
        payload = rule.payload or {}
        if rule.kind == "allowlist":
            matched = _domain_match(f.from_domain, _as_list(payload.get("domains")))
            if matched:
                return {"domain": matched}
            addresses = {a.lower() for a in _as_list(payload.get("addresses"))}
            if f.from_addr.lower() in addresses:
                return {"address": f.from_addr}
            return None

        if rule.kind == "blocklist":
            matched = _domain_match(f.from_domain, _as_list(payload.get("domains")))
            if matched:
                return {"domain": matched}
            addresses = {a.lower() for a in _as_list(payload.get("addresses"))}
            if f.from_addr.lower() in addresses:
                return {"address": f.from_addr}
            text = f"{f.subject}\n{f.normalized_text}".lower()
            hit_words = [w for w in _as_list(payload.get("keywords")) if w.lower() in text]
            if hit_words:
                return {"keywords": hit_words}
            return None

        if rule.kind == "keyword":
            text = f"{f.subject}\n{f.normalized_text}".lower()
            words = _as_list(payload.get("words") or payload.get("keywords"))
            hit = [w for w in words if w.lower() in text]
            if not hit:
                return None
            need = int(payload.get("min_hits", 1))
            return {"words": hit} if len(hit) >= need else None

        if rule.kind == "subject_regex":
            pattern = payload.get("pattern", "")
            if pattern and re.search(pattern, f.subject or "", re.I):
                return {"pattern": pattern}
            return None

        if rule.kind == "header":
            name = str(payload.get("name", "")).lower()
            value = f.headers.get(name, "")
            op = payload.get("op", "exists")
            expected = str(payload.get("value", ""))
            if op == "exists" and value:
                return {"header": name, "value": value[:200]}
            if op == "equals" and value.lower() == expected.lower():
                return {"header": name, "value": value}
            if op == "contains" and expected and expected.lower() in value.lower():
                return {"header": name, "value": value}
            if op == "missing" and not value:
                return {"header": name, "missing": True}
            return None

        if rule.kind == "auth":
            mechanisms = _as_list(payload.get("mechanisms")) or ["spf", "dkim", "dmarc"]
            wanted = set(_as_list(payload.get("results")) or ["fail"])
            observed = {m: getattr(f, m, "none") for m in mechanisms}
            bad = {m: v for m, v in observed.items() if v in wanted}
            return {"auth": bad} if bad else None

        if rule.kind == "sender_reputation":
            min_seen = int(payload.get("min_seen", 3))
            ratio = float(payload.get("spam_ratio", 0.8))
            if f.sender_seen >= min_seen and f.sender_spam_ratio >= ratio:
                return {"seen": f.sender_seen, "ratio": f.sender_spam_ratio}
            return None

        if rule.kind == "category":
            words = _as_list(payload.get("keywords") or payload.get("words"))
            text = f"{f.subject}\n{f.normalized_text}".lower()
            hit = [w for w in words if w.lower() in text]
            if not hit:
                return None
            return {"category": payload.get("category", "other"), "words": hit}

        return None
