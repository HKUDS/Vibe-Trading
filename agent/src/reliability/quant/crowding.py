"""Factor crowding diagnostics."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.reliability.quant.scorecard import ConclusionCap, QuantIssue


CrowdingTier = Literal["academic_public", "industry_known", "proprietary_variant", "novel", "unknown"]
CrowdingRisk = Literal["high", "medium", "low", "unknown"]


class FactorCrowdingReport(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    crowding_tier: CrowdingTier
    crowding_risk: CrowdingRisk
    crowding_proxy: str | None = None
    stress_periods_tested: list[str] = Field(default_factory=list)
    conclusion_cap: ConclusionCap = "paper_trade_candidate"
    warnings: list[QuantIssue] = Field(default_factory=list)
    hard_failures: list[QuantIssue] = Field(default_factory=list)


def build_crowding_report(
    *,
    crowding_tier: CrowdingTier,
    years_public: int | None = None,
    in_public_library: bool = False,
    stress_periods_tested: list[str] | None = None,
    crowding_proxy: str | None = None,
) -> FactorCrowdingReport:
    """Classify crowding risk and gate missing stress tests."""
    periods = list(stress_periods_tested or [])
    risk: CrowdingRisk
    if crowding_tier == "academic_public" and (years_public or 0) > 5 and in_public_library:
        risk = "high"
    elif crowding_tier in {"academic_public", "industry_known"}:
        risk = "medium"
    elif crowding_tier in {"proprietary_variant", "novel"}:
        risk = "low"
    else:
        risk = "unknown"

    warnings: list[QuantIssue] = []
    hard_failures: list[QuantIssue] = []
    cap: ConclusionCap = "paper_trade_candidate"
    if risk == "high":
        warnings.append(
            QuantIssue(
                code="QUANT_FACTOR_CROWDING_HIGH",
                severity="warning",
                message="historical IC may overestimate forward IC due to factor crowding",
            )
        )
        if not periods:
            cap = "research_candidate"
            hard_failures.append(
                QuantIssue(
                    code="QUANT_HIGH_CROWDING_NO_STRESS_TEST",
                    severity="hard_failure",
                    message="high crowding risk requires stress-period testing",
                )
            )

    return FactorCrowdingReport(
        crowding_tier=crowding_tier,
        crowding_risk=risk,
        crowding_proxy=crowding_proxy,
        stress_periods_tested=periods,
        conclusion_cap=cap,
        warnings=warnings,
        hard_failures=hard_failures,
    )
