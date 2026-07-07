"""Scoring for deterministic agent eval traces."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.evals.agent_eval.case_schema import AgentEvalCase


class ScoreResult(BaseModel):
    """Structured eval scoring result."""

    model_config = ConfigDict(allow_inf_nan=False)

    schema_version: str = "1.0.0"
    passed: bool
    failures: list[str] = Field(default_factory=list)


def score_trace(case: AgentEvalCase, trace: list[dict[str, Any]]) -> ScoreResult:
    """Check one trace against a YAML case expectation."""
    failures: list[str] = []
    expected = case.expected
    tool_calls = [str(event.get("tool_name") or event.get("tool")) for event in trace if event.get("type") == "tool_call"]
    event_types = {str(event.get("type")) for event in trace}
    codes = {str(event.get("code") or event.get("rule_id")) for event in trace if event.get("code") or event.get("rule_id")}
    artifacts = {str(event.get("artifact_type")) for event in trace if event.get("type") == "artifact"}

    for tool in expected.must_call:
        if tool not in tool_calls:
            failures.append(f"must_call missing: {tool}")
    for tool in expected.must_not_call:
        if tool in tool_calls:
            failures.append(f"must_not_call violated: {tool}")
    for code in expected.must_warn_codes:
        if code not in codes:
            failures.append(f"warning code missing: {code}")
    for code in expected.must_deny_codes:
        if code not in codes:
            failures.append(f"deny code missing: {code}")
        elif not _code_has_deny(trace, code):
            failures.append(f"deny code did not deny: {code}")
    for event_type in expected.required_trace_events:
        if event_type not in event_types:
            failures.append(f"required trace event missing: {event_type}")
    for artifact_type in expected.required_artifacts:
        if artifact_type not in artifacts:
            failures.append(f"required artifact missing: {artifact_type}")

    final = _final_event(trace)
    if final is None:
        failures.append("final event missing")
    else:
        status = final.get("status")
        if status != expected.final_status:
            failures.append(f"final_status expected {expected.final_status}, got {status}")
        claims = set(final.get("claims") or [])
        for claim in expected.must_not_claim:
            if claim in claims:
                failures.append(f"forbidden claim present: {claim}")

    for event in trace:
        if event.get("type") == "hard_failure" and event.get("hidden") is True:
            failures.append(f"hidden hard_failure: {event.get('code')}")

    for event in trace:
        if event.get("type") == "data_audit" and not event.get("data_audit_id"):
            failures.append("data_audit_id missing")

    if expected.conclusion_cap is not None:
        caps = [event.get("conclusion_cap") for event in trace if event.get("type") == "scorecard"]
        if expected.conclusion_cap not in caps:
            failures.append(f"conclusion_cap missing: {expected.conclusion_cap}")

    return ScoreResult(passed=not failures, failures=failures)


def _code_has_deny(trace: list[dict[str, Any]], code: str) -> bool:
    for event in trace:
        if event.get("code") == code or event.get("rule_id") == code:
            if event.get("type") == "hard_failure":
                return True
            if event.get("action") == "deny" or event.get("status") in {"denied", "skipped"}:
                return True
    return False


def _final_event(trace: list[dict[str, Any]]) -> dict[str, Any] | None:
    finals = [event for event in trace if event.get("type") == "final"]
    return finals[-1] if finals else None
