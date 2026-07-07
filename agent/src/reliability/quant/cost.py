"""Cost sensitivity and capacity diagnostics."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.reliability.quant.scorecard import ConclusionCap, QuantIssue


COST_BPS_GRID = [0, 5, 10, 25, 50, 100]
ADV_PARTICIPATION_GRID = [0.05, 0.10, 0.20]


class CostScenario(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    bps: int
    edge_after_cost_bps: float
    survives: bool


class CostSensitivityReport(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    bps_grid: list[int]
    scenarios: list[CostScenario]
    cost_breakeven_bps: float | None = None
    warnings: list[QuantIssue] = Field(default_factory=list)


class CapacityScenario(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    participation: float
    capacity_notional: float | None = None
    within_capacity: bool | None = None


class CapacityReport(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    participation: list[CapacityScenario]
    max_participation_used: float | None = None
    conclusion_cap: ConclusionCap = "paper_trade_candidate"
    warnings: list[QuantIssue] = Field(default_factory=list)


def build_cost_sensitivity_report(
    *,
    gross_edge_bps: float,
    bps_grid: list[int] | None = None,
) -> CostSensitivityReport:
    """Apply a fixed bps stress grid to a gross edge estimate."""
    grid = list(bps_grid or COST_BPS_GRID)
    scenarios = [
        CostScenario(
            bps=int(bps),
            edge_after_cost_bps=float(gross_edge_bps) - float(bps),
            survives=(float(gross_edge_bps) - float(bps)) > 0,
        )
        for bps in grid
    ]
    warnings: list[QuantIssue] = []
    ten_bps = next((scenario for scenario in scenarios if scenario.bps == 10), None)
    if ten_bps is not None and not ten_bps.survives:
        warnings.append(
            QuantIssue(
                code="QUANT_COST_SENSITIVE_10BPS_FAIL",
                severity="warning",
                message="strategy edge is non-positive after 10bps cost stress",
            )
        )
    return CostSensitivityReport(
        bps_grid=grid,
        scenarios=scenarios,
        cost_breakeven_bps=max(float(gross_edge_bps), 0.0),
        warnings=warnings,
    )


def build_capacity_report(
    *,
    order_notional_by_symbol: dict[str, float],
    adv_notional_by_symbol: dict[str, float] | None,
) -> CapacityReport:
    """Estimate ADV participation and capacity gates."""
    if not adv_notional_by_symbol:
        return CapacityReport(
            participation=[
                CapacityScenario(participation=value)
                for value in ADV_PARTICIPATION_GRID
            ],
            conclusion_cap="research_candidate",
            warnings=[
                QuantIssue(
                    code="QUANT_ADV_UNAVAILABLE",
                    severity="warning",
                    message="ADV data is unavailable; capacity is capped",
                )
            ],
        )

    total_adv = sum(max(float(value), 0.0) for value in adv_notional_by_symbol.values())
    total_order = sum(abs(float(value)) for value in order_notional_by_symbol.values())
    max_used = None if total_adv <= 0 else total_order / total_adv
    return CapacityReport(
        participation=[
            CapacityScenario(
                participation=value,
                capacity_notional=total_adv * value,
                within_capacity=(total_order <= total_adv * value),
            )
            for value in ADV_PARTICIPATION_GRID
        ],
        max_participation_used=max_used,
    )
