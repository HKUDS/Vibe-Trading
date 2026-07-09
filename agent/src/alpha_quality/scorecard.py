from __future__ import annotations

from typing import Iterable

import pandas as pd

from src.alpha_quality.execution_return import CostModel, compute_execution_return
from src.alpha_quality.forward_returns import compute_forward_return
from src.alpha_quality.ic_metrics import compute_ic_metrics
from src.alpha_quality.masks import build_ashare_tradability_mask, coverage_by_date
from src.alpha_quality.model import (
    AlphaQualityScorecard,
    CoverageMetrics,
    ExecutionMetrics,
    FactorOutputFrame,
    HorizonSplitMetrics,
    ICMetricSummary,
    PredictiveMetrics,
    ScorecardScope,
    SplitConfig,
)
from src.alpha_quality.turnover import compute_turnover, target_weights_from_factor


class NonReproducibleError(RuntimeError):
    """Raised when final-quality scorecards lack required evidence refs."""


def _empty_metrics(horizon: int, method: str) -> ICMetricSummary:
    return ICMetricSummary(
        horizon=horizon,
        rank_ic_mean=None,
        rank_ic_std=None,
        rank_icir=None,
        t_stat=None,
        t_stat_method=method,
        n_obs=0,
    )


def _split_metric(
    factor: pd.DataFrame,
    returns: pd.DataFrame,
    mask: pd.DataFrame,
    split_config: SplitConfig,
    split: str,
    horizon: int,
) -> ICMetricSummary:
    row_mask = split_config.mask_for(factor.index, split)  # type: ignore[arg-type]
    return compute_ic_metrics(
        factor.loc[row_mask],
        returns.loc[row_mask],
        horizon=horizon,
        valid_mask=mask.loc[row_mask],
    )


def compute_scorecard(
    factor_output: FactorOutputFrame,
    panel: dict[str, pd.DataFrame],
    split_config: SplitConfig,
    *,
    horizons: Iterable[int] = (1, 5, 10, 20),
    cost_profile: str = "ashare_base",
    scope: ScorecardScope = "discovery",
    data_snapshot_ref: str | None = None,
    trial_ledger_ref: str | None = None,
) -> AlphaQualityScorecard:
    if scope == "final_quality_decision" and (
        not data_snapshot_ref or not trial_ledger_ref
    ):
        raise NonReproducibleError(
            "final_quality_decision requires data_snapshot_ref and trial_ledger_ref"
        )
    close = panel.get("close")
    if close is None:
        raise ValueError("panel missing close for scorecard forward returns")

    warnings: list[str] = []
    tradability = build_ashare_tradability_mask(panel, side="long", min_amount=0.0)
    combined_mask = (
        factor_output.valid_mask.astype(bool)
        & factor_output.tradable_mask.astype(bool)
        & factor_output.universe_mask.astype(bool)
        & tradability.reindex_like(factor_output.factor).fillna(False).astype(bool)
    )

    horizon_metrics: dict[int, HorizonSplitMetrics] = {}
    horizon_values = [int(h) for h in horizons]
    for horizon in horizon_values:
        returns = compute_forward_return(close, horizon=horizon, execution_lag=1)
        by_split: dict[str, ICMetricSummary] = {}
        for split in ("train", "valid", "test"):
            if split == "test" and scope != "final_quality_decision":
                method = "standard" if horizon <= 1 else "newey_west"
                by_split[split] = _empty_metrics(horizon, method)
                if "TEST_SCOPE_HELD_OUT" not in warnings:
                    warnings.append("TEST_SCOPE_HELD_OUT")
                continue
            by_split[split] = _split_metric(
                factor_output.factor,
                returns,
                combined_mask,
                split_config,
                split,
                horizon,
            )
        horizon_metrics[horizon] = HorizonSplitMetrics(
            horizon=horizon,
            by_split=by_split,
        )

    coverage_series = coverage_by_date(combined_mask)
    coverage = CoverageMetrics(
        by_date={
            (k.date().isoformat() if isinstance(k, pd.Timestamp) else str(k)): float(v)
            for k, v in coverage_series.items()
        },
        mean_coverage=float(coverage_series.mean()) if not coverage_series.empty else None,
    )

    execution = ExecutionMetrics(uses_execution_return=False)
    if horizon_values:
        first_returns = compute_forward_return(close, horizon=horizon_values[0], execution_lag=1)
        weights = target_weights_from_factor(factor_output.factor, combined_mask)
        turnover = compute_turnover(weights)
        cost_model = CostModel(
            bps_per_one_way_turnover=10.0 if cost_profile == "ashare_base" else 0.0
        )
        net, costs = compute_execution_return(weights, first_returns, turnover, cost_model)
        execution = ExecutionMetrics(
            uses_execution_return=True,
            return_mean=float(net.mean()) if not net.empty else None,
            turnover_mean=float(turnover.mean()) if not turnover.empty else None,
            cost_bps_mean=float(costs.mean()) if not costs.empty else None,
        )
    else:
        warnings.append("EXECUTION_RETURN_MISSING")

    return AlphaQualityScorecard(
        factor_id=factor_output.factor_id,
        formula=factor_output.formula,
        factor_definition_hash=factor_output.factor_definition_hash,
        scope=scope,
        horizons=horizon_values,
        predictive=PredictiveMetrics(by_horizon=horizon_metrics),
        coverage=coverage,
        execution=execution,
        data_snapshot_ref=data_snapshot_ref,
        trial_ledger_ref=trial_ledger_ref,
        warnings=warnings,
        hard_failures=[],
    )
