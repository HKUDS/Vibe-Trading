"""Backtest reliability scorecard schema for v1.2.1 policy review."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.reliability.quant.diagnostics import (
    CapacityDiagnosticsSummary,
    DiagnosticsReadinessReport,
    ExecutionDiagnosticsSummary,
    FactorDiagnosticsSummary,
    PortfolioDiagnosticsSummary,
)
from src.reliability.quant.scorecard_explainer import ConclusionLevel, TriggeredRule

SCHEMA_VERSION = "1.2.1"


class BacktestReliabilityScorecard(BaseModel):
    """Tolerant scorecard model with optional v1.2.1 policy fields."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str = SCHEMA_VERSION
    run_id: str
    conclusion_level: ConclusionLevel = "exploratory"
    hard_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    triggered_rules: list[TriggeredRule] = Field(default_factory=list)
    policy_rule_version: str | None = None
    claim_set_ref: str | None = None
    methodology_fact_ref: str | None = None
    policy_decision_ids: list[str] = Field(default_factory=list)
    market: str | None = None
    override_attempted: bool = False
    factor_diagnostics: FactorDiagnosticsSummary | None = None
    portfolio_diagnostics: PortfolioDiagnosticsSummary | None = None
    execution_diagnostics: ExecutionDiagnosticsSummary | None = None
    capacity_diagnostics: CapacityDiagnosticsSummary | None = None
    diagnostics_readiness: DiagnosticsReadinessReport | None = None

    @field_validator("hard_failures", "warnings", "policy_decision_ids", mode="before")
    @classmethod
    def _list_fields_tolerate_missing(cls, value: object) -> object:
        return [] if value is None else value
