"""Research Card v1.2.1 contract model."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.reliability.quant.scorecard_explainer import ConclusionLevel, TriggeredRule

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


class ResearchCard(BaseModel):
    """Tolerant Research Card model with Phase 6 evidence contract fields."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = SCHEMA_VERSION
    run_id: str | None = None
    generated_at: str | None = None
    conclusion_level: ConclusionLevel | None = None
    hard_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    policy_decision_ids: list[str] = Field(default_factory=list)
    evidence_closure_summary: EvidenceClosureSummary | None = None
    claim_set_ref: str | None = None
    methodology_fact_ref: str | None = None
    scorecard_ref: str | None = None
    triggered_rules: list[TriggeredRule] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)

    @field_validator("hard_failures", "warnings", "policy_decision_ids", "claim_ids", mode="before")
    @classmethod
    def _list_fields_tolerate_missing(cls, value: object) -> object:
        return [] if value is None else value

    @field_validator("triggered_rules", mode="before")
    @classmethod
    def _triggered_rules_tolerate_missing(cls, value: object) -> object:
        return [] if value is None else value


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
