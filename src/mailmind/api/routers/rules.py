"""规则管理（黑白名单、关键词、认证、发件人信誉、分类路由）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from mailmind.api.deps import get_session, require_api_key
from mailmind.api.schemas import RuleIn, RuleOut
from mailmind.db.models import Rule

router = APIRouter(prefix="/api/v1/rules", tags=["rules"], dependencies=[Depends(require_api_key)])


class RulePatch(BaseModel):
    kind: str | None = None
    action: str | None = None
    payload: dict | None = None
    scope: str | None = None
    scope_id: str | None = None
    priority: int | None = None
    enabled: bool | None = None
    description: str | None = None


@router.get("", response_model=list[RuleOut])
def list_rules(
    kind: str | None = None,
    enabled: bool | None = None,
    session: Session = Depends(get_session),
) -> list[Rule]:
    stmt = select(Rule).order_by(Rule.priority, Rule.id)
    if kind:
        stmt = stmt.where(Rule.kind == kind)
    if enabled is not None:
        stmt = stmt.where(Rule.enabled.is_(enabled))
    return list(session.scalars(stmt).all())


@router.post("", response_model=RuleOut, status_code=201)
def create_rule(payload: RuleIn, session: Session = Depends(get_session)) -> Rule:
    rule = Rule(
        kind=payload.kind,
        action=payload.action,
        payload=payload.payload,
        scope=payload.scope,
        scope_id=payload.scope_id,
        priority=payload.priority,
        enabled=payload.enabled,
        description=payload.description,
        created_by="api",
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, payload: RulePatch, session: Session = Depends(get_session)) -> Rule:
    rule = session.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    for field in ("kind", "action", "payload", "scope", "scope_id", "priority", "enabled", "description"):
        value = getattr(payload, field)
        if value is not None:
            setattr(rule, field, value)
    session.commit()
    session.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, session: Session = Depends(get_session)) -> None:
    rule = session.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    session.delete(rule)
    session.commit()
