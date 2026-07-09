from __future__ import annotations

from typing import cast

import pandas as pd


def compute_marginal_portfolio_value(
    candidate_return: pd.Series,
    pool_returns: pd.DataFrame,
) -> dict[str, float]:
    candidate_column = "__candidate__"
    while candidate_column in pool_returns.columns:
        candidate_column = f"_{candidate_column}"
    aligned = pd.concat(
        [pool_returns, candidate_return.rename(candidate_column)],
        axis=1,
        join="inner",
    ).dropna()
    if aligned.empty:
        return {
            "portfolio_ir_before": 0.0,
            "portfolio_ir_after": 0.0,
            "delta_ir": 0.0,
            "max_drawdown_before": 0.0,
            "max_drawdown_after": 0.0,
            "delta_max_drawdown": 0.0,
            "correlation_to_pool": 0.0,
        }

    pool = aligned.drop(columns=[candidate_column])
    candidate = cast(pd.Series, aligned[candidate_column])
    before = cast(pd.Series, pool.mean(axis=1)) if not pool.empty else pd.Series(0.0, index=aligned.index)
    after = cast(pd.Series, aligned.mean(axis=1))

    before_ir = information_ratio(before)
    after_ir = information_ratio(after)
    before_mdd = max_drawdown(before)
    after_mdd = max_drawdown(after)

    return {
        "portfolio_ir_before": before_ir,
        "portfolio_ir_after": after_ir,
        "delta_ir": after_ir - before_ir,
        "max_drawdown_before": before_mdd,
        "max_drawdown_after": after_mdd,
        "delta_max_drawdown": after_mdd - before_mdd,
        "correlation_to_pool": _max_positive_corr(candidate, pool),
    }


def synergy_decision(
    result: dict[str, float],
    *,
    redundant_corr_threshold: float = 0.90,
    min_delta_ir: float = 0.0,
) -> str:
    if result.get("correlation_to_pool", 0.0) >= redundant_corr_threshold:
        return "REJECT_REDUNDANT_ALPHA"
    if result.get("delta_ir", 0.0) > min_delta_ir:
        return "ACCEPT_INCREMENTAL_ALPHA"
    return "REJECT_NO_MARGINAL_VALUE"


def information_ratio(returns: pd.Series) -> float:
    clean = returns.dropna().astype(float)
    if len(clean) < 2:
        return 0.0
    std = float(clean.std(ddof=1))
    if std <= 0:
        return 0.0
    return float(clean.mean() / std)


def max_drawdown(returns: pd.Series) -> float:
    clean = returns.fillna(0.0).astype(float)
    if clean.empty:
        return 0.0
    nav = (1.0 + clean).cumprod()
    peak = nav.cummax()
    drawdown = nav / peak - 1.0
    return float(drawdown.min())


def _max_positive_corr(candidate: pd.Series, pool: pd.DataFrame) -> float:
    if pool.empty:
        return 0.0
    corrs = [
        float(corr)
        for _, series in pool.items()
        for corr in [candidate.corr(series)]
        if pd.notna(corr)
    ]
    if not corrs:
        return 0.0
    return max(corrs)
