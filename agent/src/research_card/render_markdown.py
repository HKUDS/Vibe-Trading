"""Stable Markdown renderer for Research Cards."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from src.reliability.claims.model import ClaimSet
from src.reliability.quant.methodology_facts import MethodologyFactSet
from src.reliability.quant.scorecard import BacktestReliabilityScorecard
from src.research_card.model import ResearchCard, StructuredFailure, StructuredWarning

_SECRET_VALUE_RE = re.compile(
    r"(?i)(sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._-]{8,}|api[_-]?key\s*[:=]\s*[^,\s]+|token\s*[:=]\s*[^,\s]+)"
)


def render_research_card_markdown(
    card: ResearchCard | dict[str, Any],
    *,
    claim_set: ClaimSet | dict[str, Any] | None = None,
    methodology_facts: MethodologyFactSet | dict[str, Any] | None = None,
    scorecard: BacktestReliabilityScorecard | dict[str, Any] | None = None,
) -> str:
    """Render a deterministic Markdown Research Card snapshot."""
    card_model = card if isinstance(card, ResearchCard) else ResearchCard.model_validate(card)
    if _use_legacy_markdown(card_model, claim_set=claim_set, methodology_facts=methodology_facts, scorecard=scorecard):
        return _render_legacy_markdown(card_model)

    claim_payload = _dump_model(claim_set)
    facts_payload = _dump_model(methodology_facts)
    scorecard_payload = _dump_model(scorecard or card_model.scorecard)
    lines: list[str] = [
        f"# Research Card {card_model.run_id or card_model.title or ''}".rstrip(),
        "",
        f"- schema_version: {_clean(card_model.schema_version)}",
        f"- conclusion_level: {_clean(card_model.conclusion_level)}",
    ]
    if card_model.hypothesis:
        lines.extend(["", "## Hypothesis", "", _clean(card_model.hypothesis)])
    if card_model.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {_display_warning(item)}" for item in card_model.warnings)

    lines.extend(_render_evidence_closure(card_model))
    lines.extend(_render_policy_decisions(card_model))
    lines.extend(_render_claim_audit(card_model, claim_payload))
    lines.extend(_render_triggered_rules(card_model, scorecard_payload))
    lines.extend(_render_hard_failures(card_model, scorecard_payload))
    lines.extend(_render_diagnostics_availability(scorecard_payload))
    if facts_payload:
        lines.extend(_render_methodology_facts(facts_payload))
    return "\n".join(lines).rstrip() + "\n"


def _render_legacy_markdown(card: ResearchCard) -> str:
    lines = [
        f"# Research Card: {card.title}",
        "",
        f"- Card ID: `{card.card_id}`",
        f"- Schema Version: `{card.schema_version}`",
        f"- Conclusion: `{card.conclusion_level}`",
    ]
    if card.protocol_ref:
        lines.append(f"- Protocol: `{card.protocol_ref}`")
    if card.scorecard is not None:
        lines.append(f"- Scorecard: `{card.scorecard.scorecard_id}`")
    lines.extend(["", "## Hypothesis", "", _clean(card.hypothesis or "Not recorded.")])
    if card.key_metrics:
        lines.extend(["", "## Key Metrics", ""])
        for key, value in sorted(card.key_metrics.items()):
            lines.append(f"- {_clean(key)}: {_clean(value)}")
    if card.warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in card.warnings:
            lines.append(f"- {_display_warning(warning)}")
    if card.hard_failures:
        lines.extend(["", "## Hard Failures", ""])
        for failure in card.hard_failures:
            lines.append(f"- {_display_failure(failure)}")
    return "\n".join(lines) + "\n"


def _render_evidence_closure(card: ResearchCard) -> list[str]:
    summary = card.evidence_closure_summary
    lines = ["", "## Evidence Closure"]
    if summary is None:
        return [*lines, "- status: not recorded"]
    status = "passed" if summary.passed else "failed"
    if summary.degraded:
        status += " degraded"
    lines.append(f"- status: {status}")
    if summary.verified_from:
        lines.append(f"- verified_from: {_clean(', '.join(summary.verified_from))}")
    for label, values in (
        ("missing_refs", summary.missing_refs),
        ("dangling_refs", summary.dangling_refs),
        ("inconsistent_ids", summary.inconsistent_ids),
        ("outbox_pending", summary.outbox_pending),
        ("degraded_reasons", summary.degraded_reasons),
    ):
        if values:
            lines.append(f"- {label}: {_clean(', '.join(values))}")
    return lines


def _render_policy_decisions(card: ResearchCard) -> list[str]:
    lines = ["", "## Policy Decisions"]
    decision_ids = card.policy_decision_ids or card.policy_decision_refs
    if not decision_ids:
        return [*lines, "- none recorded"]
    lines.extend(f"- {_clean(decision_id)}" for decision_id in decision_ids)
    return lines


def _render_claim_audit(card: ResearchCard, claim_payload: dict[str, Any]) -> list[str]:
    lines = ["", "## Claim Audit"]
    claims = claim_payload.get("claims") if claim_payload else None
    if isinstance(claims, list) and claims:
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            lines.append(
                "- "
                + " | ".join(
                    [
                        _clean(claim.get("claim_id")),
                        _clean(claim.get("claim_type")),
                        _clean(claim.get("claim_text")),
                    ]
                )
            )
        return lines
    if card.claim_ids:
        lines.extend(f"- {_clean(claim_id)}" for claim_id in card.claim_ids)
    else:
        lines.append("- none recorded")
    return lines


def _render_triggered_rules(card: ResearchCard, scorecard_payload: dict[str, Any]) -> list[str]:
    lines = ["", "## Triggered Rules"]
    rules = [rule.model_dump(mode="json") for rule in card.triggered_rules]
    if not rules and isinstance(scorecard_payload.get("triggered_rules"), list):
        rules = [rule for rule in scorecard_payload["triggered_rules"] if isinstance(rule, dict)]
    if not rules:
        return [*lines, "- none recorded"]
    for rule in rules:
        refs = ", ".join(str(ref) for ref in rule.get("evidence_refs") or [])
        lines.append(
            "- "
            + " | ".join(
                [
                    _clean(rule.get("rule_id")),
                    _clean(rule.get("reason_code")),
                    _clean(rule.get("explanation")),
                    _clean(refs),
                ]
            )
        )
    return lines


def _render_hard_failures(card: ResearchCard, scorecard_payload: dict[str, Any]) -> list[str]:
    lines = ["", "## Hard Failures"]
    failures = list(card.hard_failures)
    if not failures and isinstance(scorecard_payload.get("hard_failures"), list):
        failures = list(scorecard_payload["hard_failures"])
    if not failures:
        return [*lines, "- none"]
    lines.extend(f"- {_display_failure(item)}" for item in failures)
    return lines


def _render_methodology_facts(facts_payload: dict[str, Any]) -> list[str]:
    lines = ["", "## Methodology Facts"]
    for key in (
        "has_registered_protocol",
        "trial_count",
        "has_data_audit",
        "pit_safe",
        "has_cost_model",
        "has_benchmark",
        "has_oos",
        "has_policy_denies",
    ):
        if key in facts_payload:
            lines.append(f"- {key}: {_clean(facts_payload.get(key))}")
    return lines


def _render_diagnostics_availability(scorecard_payload: dict[str, Any]) -> list[str]:
    readiness = scorecard_payload.get("diagnostics_readiness")
    if not isinstance(readiness, dict):
        return []
    lines = ["", "## Diagnostics Availability"]
    lines.append(f"- note: {_clean(readiness.get('note') or 'readiness only; not production diagnostics')}")
    gaps = [str(item) for item in readiness.get("readiness_gaps") or []]
    if gaps:
        lines.append(f"- readiness_gaps: {_clean(', '.join(gaps))}")
    else:
        lines.append("- readiness_gaps: none")
    for section in ("factor", "portfolio", "execution", "capacity"):
        summary = readiness.get(section)
        if not isinstance(summary, dict):
            continue
        section_gaps = [str(item) for item in summary.get("readiness_gaps") or []]
        status = "ready" if not section_gaps else "gaps"
        detail = ", ".join(section_gaps) if section_gaps else "none"
        lines.append(f"- {section}: {status} ({_clean(detail)})")
    return lines


def _use_legacy_markdown(
    card: ResearchCard,
    *,
    claim_set: Any,
    methodology_facts: Any,
    scorecard: Any,
) -> bool:
    return not any(
        [
            claim_set,
            methodology_facts,
            scorecard,
            card.evidence_closure_summary,
            card.policy_decision_ids,
            card.claim_ids,
            card.triggered_rules,
            card.claim_set_ref,
            card.methodology_fact_ref,
            card.scorecard_ref,
        ]
    )


def _dump_model(value: BaseModel | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return dict(value)


def _display_warning(value: StructuredWarning | str) -> str:
    if isinstance(value, StructuredWarning):
        return f"`{_clean(value.code)}` ({_clean(value.severity)}): {_clean(value.message)}"
    return _clean(value)


def _display_failure(value: StructuredFailure | dict[str, Any] | str) -> str:
    if isinstance(value, StructuredFailure):
        return f"`{_clean(value.code)}` ({_clean(value.severity)}): {_clean(value.message)}"
    if isinstance(value, dict) and value.get("code"):
        severity = value.get("severity") or "hard_failure"
        return f"`{_clean(value.get('code'))}` ({_clean(severity)}): {_clean(value.get('message') or '')}"
    return _clean(value)


def _clean(value: Any) -> str:
    text = "" if value is None else str(value)
    return _SECRET_VALUE_RE.sub("[REDACTED]", text)
