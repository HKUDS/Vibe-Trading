"""Experimental overfit diagnostics for DSR/PBO."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from scipy.stats import norm

from src.reliability.quant.scorecard import QuantIssue


class OverfitExperimentalResult(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    experimental_metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[QuantIssue] = Field(default_factory=list)
    hard_failures: list[QuantIssue] = Field(default_factory=list)


def build_overfit_experimental_metrics(
    *,
    observed_sharpe: float,
    benchmark_sharpe: float,
    sharpe_std: float,
    n_observations: int,
    n_trials: int | None,
) -> OverfitExperimentalResult:
    """Return DSR/PBO as experimental-only diagnostics."""
    warnings: list[QuantIssue] = []
    metrics: dict[str, Any] = {
        "pbo": {
            "experimental": True,
            "value": None,
            "method": "placeholder_v1",
        }
    }

    if n_trials is None:
        warnings.append(
            QuantIssue(
                code="QUANT_TRIAL_COUNT_MISSING_FOR_DSR",
                severity="warning",
                message="trial_count is required to compute DSR",
            )
        )
        return OverfitExperimentalResult(experimental_metrics=metrics, warnings=warnings)

    trials = max(int(n_trials), 1)
    observations = max(int(n_observations), 1)
    std = max(float(sharpe_std), 1e-12)
    multiple_testing_threshold = norm.ppf(1.0 - 0.05 / trials)
    z_score = (float(observed_sharpe) - float(benchmark_sharpe)) * math.sqrt(observations) / std
    dsr = float(norm.cdf(z_score - multiple_testing_threshold))
    metrics["dsr"] = {
        "experimental": True,
        "value": round(dsr, 6),
        "n_trials": trials,
        "n_observations": observations,
    }
    if dsr < 0.95:
        warnings.append(
            QuantIssue(
                code="QUANT_DSR_BELOW_095_EXPERIMENTAL",
                severity="warning",
                message="experimental DSR is below 0.95",
                metadata={"dsr": dsr},
            )
        )
    return OverfitExperimentalResult(experimental_metrics=metrics, warnings=warnings)
