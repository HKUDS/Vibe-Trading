from __future__ import annotations

from typing import Literal

import pandas as pd


def target_weights_from_factor(
    factor: pd.DataFrame,
    valid_mask: pd.DataFrame,
    *,
    method: Literal["quantile_ls", "rank_long_short"] = "rank_long_short",
    long_quantile: float = 0.2,
    short_quantile: float = 0.2,
    gross_leverage: float = 1.0,
) -> pd.DataFrame:
    if method not in {"quantile_ls", "rank_long_short"}:
        raise ValueError(f"unsupported weighting method: {method}")
    weights = pd.DataFrame(0.0, index=factor.index, columns=factor.columns)
    for dt in factor.index:
        valid = valid_mask.loc[dt] & factor.loc[dt].notna()
        row = factor.loc[dt, valid]
        if len(row) < 2:
            continue
        ranks = row.rank(method="first", pct=True)
        longs = ranks >= (1.0 - long_quantile)
        shorts = ranks <= short_quantile
        if longs.any():
            weights.loc[dt, row.index[longs]] = gross_leverage / 2.0 / int(longs.sum())
        if shorts.any():
            weights.loc[dt, row.index[shorts]] = -gross_leverage / 2.0 / int(shorts.sum())
    return weights


def compute_turnover(weights: pd.DataFrame) -> pd.Series:
    return 0.5 * weights.diff().abs().sum(axis=1)
