"""Execution realism diagnostics."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.reliability.quant.scorecard import ExecutionTimestampSet, QuantIssue


REQUIRED_EXECUTION_FIELDS = [
    "signal_time",
    "decision_time",
    "order_time",
    "fill_time",
    "price_time",
]


class ExecutionRealismReport(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    required_fields: list[str]
    missing_fields: list[str]
    passed: bool
    warnings: list[QuantIssue] = Field(default_factory=list)


def build_execution_realism_report(timestamps: ExecutionTimestampSet) -> ExecutionRealismReport:
    """Report whether execution timing evidence is complete."""
    missing = timestamps.missing_fields()
    warnings = []
    if missing:
        warnings.append(
            QuantIssue(
                code="QUANT_EXECUTION_TIMESTAMPS_MISSING",
                severity="warning",
                message="execution timestamp evidence is incomplete",
                metadata={"missing": missing},
            )
        )
    return ExecutionRealismReport(
        required_fields=list(REQUIRED_EXECUTION_FIELDS),
        missing_fields=missing,
        passed=not missing,
        warnings=warnings,
    )
