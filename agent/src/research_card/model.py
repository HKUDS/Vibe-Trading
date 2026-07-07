"""Schema-versioned Research Card delivery model."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.reliability.quant.scorecard import BacktestReliabilityScorecard
from src.reliability.quant.scorecard_explainer import ConclusionLevel, TriggeredRule
from src.reliability.redaction import redact_secrets


RESEARCH_CARD_SCHEMA_VERSION = "1.0.0"
SCHEMA_VERSION = "1.2.1"


class EvidenceClosureSummary(BaseModel):
    """Small Research Card/API/UI summary of an EvidenceClosureReport."""

    schema_version: str = SCHEMA_VERSION
    passed: bool
    degraded: bool = False
    verified_from: list[str] = Field(default_factory=list)
    missing_refs: list[str] = Field(default_factory=list)
    dangling_refs: list[str] = Field(default_factory=list)
    inconsistent_ids: list[str] = Field(default_factory=list)
    outbox_pending: list[str] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)
    hard_failure_inconsistencies: list[str] = Field(default_factory=list)


class StructuredWarning(BaseModel):
    """Stable warning code rendered in Research Cards and panels."""

    model_config = ConfigDict(allow_inf_nan=False)

    code: str
    severity: Literal["info", "warning", "hard_failure"] = "warning"
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _redact(cls, value: Any) -> Any:
        return redact_secrets(value)


class StructuredFailure(BaseModel):
    """Stable hard-failure code rendered in Research Cards and panels."""

    model_config = ConfigDict(allow_inf_nan=False)

    code: str
    severity: Literal["hard_failure"] = "hard_failure"
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _redact(cls, value: Any) -> Any:
        return redact_secrets(value)


class ResearchCard(BaseModel):
    """Machine-readable, auditable research delivery card."""

    model_config = ConfigDict(allow_inf_nan=False, arbitrary_types_allowed=False, extra="allow")

    card_id: str = ""
    schema_version: str = RESEARCH_CARD_SCHEMA_VERSION
    run_id: str | None = None
    generated_at: str | None = None
    title: str = ""
    protocol_ref: str | None = None
    hypothesis: str | None = None
    universe: dict[str, Any] = Field(default_factory=dict)
    data_sources: list[dict[str, Any]] = Field(default_factory=list)
    data_audit_refs: list[str] = Field(default_factory=list)
    policy_decision_refs: list[str] = Field(default_factory=list)
    policy_decision_ids: list[str] = Field(default_factory=list)
    tool_trace_refs: list[str] = Field(default_factory=list)
    backtest_refs: list[str] = Field(default_factory=list)
    alpha_bench_refs: list[str] = Field(default_factory=list)
    scorecard: BacktestReliabilityScorecard | None = None
    key_metrics: dict[str, Any] = Field(default_factory=dict)
    benchmark: dict[str, Any] = Field(default_factory=dict)
    cost_model: dict[str, Any] = Field(default_factory=dict)
    execution_assumptions: dict[str, Any] = Field(default_factory=dict)
    oos_results: dict[str, Any] = Field(default_factory=dict)
    warnings: list[StructuredWarning | str] = Field(default_factory=list)
    hard_failures: list[StructuredFailure | str] = Field(default_factory=list)
    reproducibility: dict[str, Any] = Field(default_factory=dict)
    conclusion_level: ConclusionLevel = "exploratory"
    evidence_closure_summary: EvidenceClosureSummary | None = None
    claim_set_ref: str | None = None
    methodology_fact_ref: str | None = None
    scorecard_ref: str | None = None
    triggered_rules: list[TriggeredRule] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _redact_untrusted_content(cls, value: Any) -> Any:
        redacted = redact_secrets(value)
        if isinstance(redacted, dict):
            data = dict(redacted)
            if not data.get("card_id"):
                data["card_id"] = str(data.get("run_id") or "research_card")
            if not data.get("title"):
                data["title"] = str(data.get("run_id") or "Research Card")
            return data
        return redacted

    @field_validator(
        "data_audit_refs",
        "policy_decision_refs",
        "policy_decision_ids",
        "tool_trace_refs",
        "backtest_refs",
        "alpha_bench_refs",
        "warnings",
        "hard_failures",
        "triggered_rules",
        "claim_ids",
        mode="before",
    )
    @classmethod
    def _list_fields_tolerate_missing(cls, value: object) -> object:
        return [] if value is None else value

    @model_validator(mode="after")
    def _hard_failures_force_not_reliable(self) -> "ResearchCard":
        if self.hard_failures:
            self.conclusion_level = "not_reliable"
        return self


def evidence_closure_summary_from_report(report: Any) -> EvidenceClosureSummary:
    """Project a full EvidenceClosureReport into a stable card/UI summary."""
    return EvidenceClosureSummary(
        passed=bool(getattr(report, "passed", False)),
        degraded=bool(getattr(report, "degraded", False)),
        verified_from=list(getattr(report, "verified_from", []) or []),
        missing_refs=list(getattr(report, "missing_refs", []) or []),
        dangling_refs=list(getattr(report, "dangling_refs", []) or []),
        inconsistent_ids=list(getattr(report, "inconsistent_ids", []) or []),
        outbox_pending=list(getattr(report, "outbox_pending", []) or []),
        degraded_reasons=list(getattr(report, "degraded_reasons", []) or []),
        hard_failure_inconsistencies=list(getattr(report, "hard_failure_inconsistencies", []) or []),
    )
