"""Regime-conditional IC diagnostics."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.reliability.quant.scorecard import ConclusionCap, QuantIssue


RegimeName = Literal["bull_market", "bear_market", "sideways", "full_sample"]


class RegimeLabelArtifactRef(BaseModel):
    """Reference to PIT-safe regime labels stored as an artifact."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, arbitrary_types_allowed=False)

    artifact_ref: str
    sha256: str
    calendar: str
    as_of_policy: str

    @model_validator(mode="before")
    @classmethod
    def _reject_pandas_objects(cls, value: Any) -> Any:
        if isinstance(value, dict):
            for item in value.values():
                module = type(item).__module__
                name = type(item).__name__
                if module.startswith("pandas.") and name in {"Series", "DataFrame"}:
                    raise ValueError("regime labels must be referenced by artifact, not embedded pandas objects")
        return value


class RegimeICReport(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    regime_ic: dict[RegimeName, float]
    regime_frequency: dict[Literal["bull_market", "bear_market", "sideways"], float]
    regime_stability_score: float | None = None
    conclusion_cap: ConclusionCap = "paper_trade_candidate"
    warnings: list[QuantIssue] = Field(default_factory=list)
    hard_failures: list[QuantIssue] = Field(default_factory=list)


def build_regime_ic_report(
    *,
    regime_ic: dict[RegimeName, float],
    regime_frequency: dict[Literal["bull_market", "bear_market", "sideways"], float],
    regime_activation: bool,
) -> RegimeICReport:
    """Build a regime IC report and gate negative high-frequency regimes."""
    warnings: list[QuantIssue] = []
    hard_failures: list[QuantIssue] = []
    cap: ConclusionCap = "paper_trade_candidate"

    non_full = [
        float(regime_ic[name])
        for name in ("bull_market", "bear_market", "sideways")
        if name in regime_ic
    ]
    denominator = abs(sum(non_full) / len(non_full)) if non_full else 0.0
    if denominator < 0.005:
        stability = None
        warnings.append(
            QuantIssue(
                code="QUANT_REGIME_STABILITY_DENOMINATOR_NEAR_ZERO",
                severity="warning",
                message="regime stability denominator is near zero",
            )
        )
    else:
        stability = min(non_full) / denominator

    for regime, frequency in regime_frequency.items():
        ic_value = regime_ic.get(regime)
        if ic_value is not None and frequency > 0.20 and ic_value < -0.01 and not regime_activation:
            cap = "research_candidate"
            hard_failures.append(
                QuantIssue(
                    code="QUANT_REGIME_NEGATIVE_IC_NO_ACTIVATION",
                    severity="hard_failure",
                    message="negative IC in frequent regime requires regime activation",
                    metadata={"regime": regime, "frequency": frequency, "ic": ic_value},
                )
            )

    return RegimeICReport(
        regime_ic=regime_ic,
        regime_frequency=regime_frequency,
        regime_stability_score=stability,
        conclusion_cap=cap,
        warnings=warnings,
        hard_failures=hard_failures,
    )
