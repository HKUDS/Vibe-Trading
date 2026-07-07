"""Factor evaluation diagnostics for quant reliability scorecards."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from src.reliability.quant.scorecard import QuantIssue


DEFAULT_IC_HORIZONS = [1, 5, 20]
_IC_DENOMINATOR_EPSILON = 0.005


class ICHorizonMetric(BaseModel):
    """IC statistic for one forward-return horizon."""

    model_config = ConfigDict(allow_inf_nan=False)

    horizon: int
    ic: float | None = None
    decay_to_1d: float | None = None


class WalkForwardReport(BaseModel):
    """Walk-forward reliability gate."""

    model_config = ConfigDict(allow_inf_nan=False)

    fold_count: int | None = None
    effective_fold_count: int
    oos_ic_mean: float | None = None
    is_ic_mean: float | None = None
    oos_is_ic_ratio: float | None = None
    negative_oos_fold_ratio: float | None = None
    oos_ir: float | None = None
    max_oos_drawdown: float | None = None
    max_is_drawdown: float | None = None
    max_oos_drawdown_duration: int | None = None
    max_is_drawdown_duration: int | None = None
    passed: bool
    failure_reasons: list[str] = Field(default_factory=list)
    warnings: list[QuantIssue] = Field(default_factory=list)
    hard_failures: list[QuantIssue] = Field(default_factory=list)


def resolve_ic_horizons(evaluation_plan: Any | None) -> list[int]:
    """Return IC horizons from a ResearchProtocol evaluation plan or defaults."""
    raw = getattr(evaluation_plan, "ic_horizons", None)
    if raw:
        return [int(horizon) for horizon in raw]
    return list(DEFAULT_IC_HORIZONS)


class _ICHorizonReportBuilder:
    """Callable IC-horizon report builder with a price-frame convenience method."""

    def __call__(
        self,
        ic_by_horizon: Mapping[int, float | None],
        *,
        horizons: list[int] | None = None,
    ) -> tuple[list[ICHorizonMetric], list[QuantIssue]]:
        horizons = list(horizons or DEFAULT_IC_HORIZONS)
        ic_1d = ic_by_horizon.get(1)
        warnings: list[QuantIssue] = []
        decay_allowed = ic_1d is not None and abs(float(ic_1d)) >= _IC_DENOMINATOR_EPSILON
        if not decay_allowed:
            warnings.append(
                QuantIssue(
                    code="QUANT_IC_DECAY_DENOMINATOR_NEAR_ZERO",
                    severity="warning",
                    message="IC_1d is near zero; IC decay is not computed",
                    metadata={"ic_1d": ic_1d},
                )
            )

        report: list[ICHorizonMetric] = []
        for horizon in horizons:
            ic_value = ic_by_horizon.get(horizon)
            decay = None
            if decay_allowed and ic_value is not None:
                decay = float(ic_value) / float(ic_1d)
            report.append(
                ICHorizonMetric(
                    horizon=int(horizon),
                    ic=float(ic_value) if ic_value is not None else None,
                    decay_to_1d=decay,
                )
            )
        return report, warnings

    def from_prices(
        self,
        factor_df: pd.DataFrame,
        close_df: pd.DataFrame,
        *,
        horizons: list[int] | None = None,
    ) -> tuple[list[ICHorizonMetric], list[QuantIssue]]:
        """Compute horizon IC from factor values and close-price panels."""
        from src.factors.factor_analysis_core import compute_ic_series

        horizons = list(horizons or DEFAULT_IC_HORIZONS)
        values: dict[int, float | None] = {}
        for horizon in horizons:
            forward_returns = close_df.pct_change(periods=horizon).shift(-horizon)
            ic = compute_ic_series(factor_df, forward_returns)
            values[horizon] = float(ic.mean()) if not ic.empty else None
        return self(values, horizons=horizons)


build_ic_horizon_report = _ICHorizonReportBuilder()


def build_walk_forward_report(
    *,
    effective_fold_count: int,
    is_ic_mean: float | None,
    oos_ic_mean: float | None,
    oos_ir: float | None = None,
    negative_oos_fold_ratio: float | None = None,
    fold_count: int | None = None,
    max_oos_drawdown: float | None = None,
    max_is_drawdown: float | None = None,
    max_oos_drawdown_duration: int | None = None,
    max_is_drawdown_duration: int | None = None,
) -> WalkForwardReport:
    """Build a walk-forward report with fixed Phase 5 failure definitions."""
    failure_reasons: list[str] = []
    hard_failures: list[QuantIssue] = []
    ratio: float | None = None

    if effective_fold_count < 6:
        failure_reasons.append("effective_fold_count < 6")
    if oos_ic_mean is not None and oos_ic_mean < 0:
        failure_reasons.append("OOS IC mean < 0")
    if oos_ir is not None and oos_ir < 0:
        failure_reasons.append("OOS IR < 0")
    if negative_oos_fold_ratio is not None and negative_oos_fold_ratio > 0.40:
        failure_reasons.append("negative OOS fold ratio > 40%")

    if is_ic_mean is not None and abs(is_ic_mean) < _IC_DENOMINATOR_EPSILON:
        failure_reasons.append("abs(IS IC mean) < 0.005")
        hard_failures.append(
            QuantIssue(
                code="QUANT_IS_IC_NEAR_ZERO",
                severity="hard_failure",
                message="IS IC mean is near zero; OOS/IS ratio is not meaningful",
                metadata={"is_ic_mean": is_ic_mean},
            )
        )
    elif is_ic_mean not in (None, 0) and oos_ic_mean is not None:
        ratio = float(oos_ic_mean) / float(is_ic_mean)
        if ratio < 0.3:
            failure_reasons.append("OOS/IS IC ratio < 0.3")

    if (
        max_oos_drawdown is not None
        and max_is_drawdown is not None
        and abs(max_oos_drawdown) > 2 * abs(max_is_drawdown)
    ):
        failure_reasons.append("max OOS drawdown > 2x IS")
    if (
        max_oos_drawdown_duration is not None
        and max_is_drawdown_duration is not None
        and max_oos_drawdown_duration > 2 * max_is_drawdown_duration
    ):
        failure_reasons.append("max OOS drawdown duration > 2x IS")

    return WalkForwardReport(
        fold_count=fold_count,
        effective_fold_count=effective_fold_count,
        oos_ic_mean=oos_ic_mean,
        is_ic_mean=is_ic_mean,
        oos_is_ic_ratio=ratio,
        negative_oos_fold_ratio=negative_oos_fold_ratio,
        oos_ir=oos_ir,
        max_oos_drawdown=max_oos_drawdown,
        max_is_drawdown=max_is_drawdown,
        max_oos_drawdown_duration=max_oos_drawdown_duration,
        max_is_drawdown_duration=max_is_drawdown_duration,
        passed=not failure_reasons and not hard_failures,
        failure_reasons=failure_reasons,
        hard_failures=hard_failures,
    )
