from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class CostModel:
    bps_per_one_way_turnover: float = 10.0

    def estimate_bps(self, *, turnover: pd.Series, weights: pd.DataFrame) -> pd.Series:  # noqa: ARG002
        return turnover.fillna(0.0) * self.bps_per_one_way_turnover


def compute_execution_return(
    weights: pd.DataFrame,
    forward_returns: pd.DataFrame,
    turnover: pd.Series,
    cost_model: CostModel,
) -> tuple[pd.Series, pd.Series]:
    aligned_returns = forward_returns.reindex(index=weights.index, columns=weights.columns)
    gross = (weights.shift(1) * aligned_returns).sum(axis=1)
    cost_bps = cost_model.estimate_bps(turnover=turnover, weights=weights)
    return gross - cost_bps / 10000.0, cost_bps
