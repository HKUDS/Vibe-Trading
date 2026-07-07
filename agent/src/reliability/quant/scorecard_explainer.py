"""Explainable scorecard policy trigger records."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.2.1"

RuleAction = Literal["hard_fail", "cap_conclusion", "warn"]
ConclusionLevel = Literal["not_reliable", "exploratory", "research_candidate", "paper_trade_candidate", "production_ready"]


class TriggeredRule(BaseModel):
    """One policy rule triggered during scorecard review."""

    schema_version: str = SCHEMA_VERSION
    rule_id: str
    reason_code: str
    action: RuleAction
    explanation: str
    evidence_refs: list[str] = Field(default_factory=list)
    conclusion_cap: ConclusionLevel | None = None


def format_triggered_rule(
    *,
    rule: Any,
    explanation_context: dict[str, Any],
    evidence_refs: list[str],
) -> TriggeredRule:
    """Create a stable TriggeredRule from a policy rule and predicate context."""
    template = str(rule.explanation_template or rule.rule_id)
    try:
        explanation = template.format(**explanation_context)
    except KeyError:
        explanation = template
    return TriggeredRule(
        rule_id=rule.rule_id,
        reason_code=rule.reason_code,
        action=rule.action,
        explanation=explanation,
        evidence_refs=list(evidence_refs),
        conclusion_cap=rule.conclusion_cap,
    )
