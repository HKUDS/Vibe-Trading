"""Optional quant diagnostics readiness schemas for v1.2.1."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.2.1"
READINESS_NOTE = "readiness only; not production diagnostics"


class FactorDiagnosticsSummary(BaseModel):
    """Readiness signals for future factor diagnostics."""

    schema_version: str = SCHEMA_VERSION
    data_audit_available: bool | None = None
    pit_safe: bool | None = None
    benchmark_available: bool | None = None
    oos_available: bool | None = None
    trial_count: int | None = None
    readiness_gaps: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("trial_count")
    @classmethod
    def _trial_count_non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("trial_count must be non-negative")
        return value


class PortfolioDiagnosticsSummary(BaseModel):
    """Readiness signals for future portfolio diagnostics."""

    schema_version: str = SCHEMA_VERSION
    cost_model_available: bool | None = None
    market_rule_coverage_available: bool | None = None
    readiness_gaps: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ExecutionDiagnosticsSummary(BaseModel):
    """Readiness signals for future execution diagnostics."""

    schema_version: str = SCHEMA_VERSION
    execution_timeline_available: bool | None = None
    timestamps_present: list[str] = Field(default_factory=list)
    readiness_gaps: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CapacityDiagnosticsSummary(BaseModel):
    """Readiness signals for future capacity diagnostics."""

    schema_version: str = SCHEMA_VERSION
    capacity_test_available: bool | None = None
    adv_caps_tested: list[float] = Field(default_factory=list)
    readiness_gaps: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DiagnosticsReadinessReport(BaseModel):
    """Aggregate readiness report for optional future quant diagnostics."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str = SCHEMA_VERSION
    run_id: str | None = None
    factor: FactorDiagnosticsSummary | None = None
    portfolio: PortfolioDiagnosticsSummary | None = None
    execution: ExecutionDiagnosticsSummary | None = None
    capacity: CapacityDiagnosticsSummary | None = None
    readiness_gaps: list[str] = Field(default_factory=list)
    generated_from_artifacts: list[str] = Field(default_factory=list)
    note: str = READINESS_NOTE

    @classmethod
    def from_methodology_facts(cls, facts: Any) -> "DiagnosticsReadinessReport":
        """Build a readiness report from MethodologyFactSet-like facts."""
        gaps: list[str] = []
        factor_gaps = _gaps_for(
            [
                ("factor_data_audit_missing", getattr(facts, "has_data_audit", False)),
                ("factor_pit_status_missing", getattr(facts, "pit_safe", None) is not None),
                ("factor_benchmark_missing", getattr(facts, "has_benchmark", False)),
                ("factor_oos_missing", getattr(facts, "has_oos", False)),
                ("factor_trial_count_missing", getattr(facts, "trial_count", None) is not None),
            ]
        )
        portfolio_gaps = _gaps_for(
            [
                ("portfolio_cost_model_missing", getattr(facts, "has_cost_model", False)),
                ("portfolio_market_rules_missing", getattr(facts, "has_market_rule_coverage", False)),
            ]
        )
        execution_gaps = _gaps_for(
            [
                ("execution_timeline_missing", getattr(facts, "has_execution_timeline", False)),
            ]
        )
        capacity_gaps = _gaps_for(
            [
                ("capacity_test_missing", getattr(facts, "has_capacity_test", False)),
            ]
        )
        for source in (factor_gaps, portfolio_gaps, execution_gaps, capacity_gaps):
            for gap in source:
                _append_unique(gaps, gap)

        return cls(
            run_id=getattr(facts, "run_id", None),
            factor=FactorDiagnosticsSummary(
                data_audit_available=getattr(facts, "has_data_audit", None),
                pit_safe=getattr(facts, "pit_safe", None),
                benchmark_available=getattr(facts, "has_benchmark", None),
                oos_available=getattr(facts, "has_oos", None),
                trial_count=getattr(facts, "trial_count", None),
                readiness_gaps=factor_gaps,
            ),
            portfolio=PortfolioDiagnosticsSummary(
                cost_model_available=getattr(facts, "has_cost_model", None),
                market_rule_coverage_available=getattr(facts, "has_market_rule_coverage", None),
                readiness_gaps=portfolio_gaps,
            ),
            execution=ExecutionDiagnosticsSummary(
                execution_timeline_available=getattr(facts, "has_execution_timeline", None),
                timestamps_present=list(getattr(facts, "execution_timestamps_present", []) or []),
                readiness_gaps=execution_gaps,
            ),
            capacity=CapacityDiagnosticsSummary(
                capacity_test_available=getattr(facts, "has_capacity_test", None),
                adv_caps_tested=[float(value) for value in getattr(facts, "adv_caps_tested", []) or []],
                readiness_gaps=capacity_gaps,
            ),
            readiness_gaps=gaps,
            generated_from_artifacts=list(getattr(facts, "generated_from_artifacts", []) or []),
        )


def _gaps_for(checks: list[tuple[str, bool]]) -> list[str]:
    return [gap for gap, present in checks if not present]


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
