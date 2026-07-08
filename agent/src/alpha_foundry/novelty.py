from __future__ import annotations

from dataclasses import dataclass
from math import isnan

import pandas as pd


@dataclass(frozen=True)
class NoveltyMetrics:
    max_factor_rank_corr_to_existing: float
    nearest_existing_factor_id: str | None
    max_abs_factor_rank_corr_to_existing: float
    comparable_existing_count: int


def compute_novelty(
    *,
    candidate: pd.DataFrame,
    existing: dict[str, pd.DataFrame],
    min_cross_section: int = 2,
) -> NoveltyMetrics:
    """Compare a candidate factor panel with existing factors by date rank correlation."""

    best_corr = float("-inf")
    best_abs_corr = 0.0
    best_factor_id: str | None = None
    comparable = 0

    for factor_id, panel in existing.items():
        corr = _average_rank_corr(candidate, panel, min_cross_section=min_cross_section)
        if corr is None:
            continue
        comparable += 1
        if corr > best_corr:
            best_corr = corr
            best_factor_id = factor_id
        best_abs_corr = max(best_abs_corr, abs(corr))

    if comparable == 0:
        best_corr = 0.0

    return NoveltyMetrics(
        max_factor_rank_corr_to_existing=best_corr,
        nearest_existing_factor_id=best_factor_id,
        max_abs_factor_rank_corr_to_existing=best_abs_corr,
        comparable_existing_count=comparable,
    )


def novelty_decision(
    metrics: NoveltyMetrics,
    *,
    duplicate_corr_threshold: float = 0.90,
) -> str | None:
    if metrics.max_factor_rank_corr_to_existing >= duplicate_corr_threshold:
        return "DUPLICATE_ALPHA"
    return None


def novelty_score(metrics: NoveltyMetrics) -> float:
    if isnan(metrics.max_abs_factor_rank_corr_to_existing):
        return 1.0
    return max(0.0, min(1.0, 1.0 - metrics.max_abs_factor_rank_corr_to_existing))


def _average_rank_corr(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    min_cross_section: int,
) -> float | None:
    dates = left.index.intersection(right.index)
    corrs: list[float] = []
    for date in dates:
        lrow = left.loc[date]
        rrow = right.loc[date]
        symbols = lrow.index.intersection(rrow.index)
        if len(symbols) < min_cross_section:
            continue
        paired = pd.concat(
            [lrow.loc[symbols].rename("left"), rrow.loc[symbols].rename("right")],
            axis=1,
        ).dropna()
        if len(paired) < min_cross_section:
            continue
        corr = paired["left"].rank(method="average").corr(
            paired["right"].rank(method="average")
        )
        if pd.notna(corr):
            corrs.append(float(corr))
    if not corrs:
        return None
    return float(sum(corrs) / len(corrs))
