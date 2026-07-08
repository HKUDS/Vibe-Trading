from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.alpha_quality.model import ICMetricSummary


def _align_three(
    factor: pd.DataFrame, returns: pd.DataFrame, mask: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = factor.index.intersection(returns.index).intersection(mask.index)
    symbols = factor.columns.intersection(returns.columns).intersection(mask.columns)
    return (
        factor.loc[dates, symbols],
        returns.loc[dates, symbols],
        mask.loc[dates, symbols].astype(bool),
    )


def compute_ic_series_safe(
    factor: pd.DataFrame,
    forward_return: pd.DataFrame,
    mask: pd.DataFrame,
    *,
    min_cross_section: int = 5,
) -> pd.Series:
    factor, forward_return, mask = _align_three(factor, forward_return, mask)
    values: list[float] = []
    dates: list[pd.Timestamp] = []
    for dt in factor.index:
        valid = mask.loc[dt] & factor.loc[dt].notna() & forward_return.loc[dt].notna()
        if int(valid.sum()) < min_cross_section:
            continue
        f = factor.loc[dt, valid].rank(method="average")
        r = forward_return.loc[dt, valid].rank(method="average")
        corr = f.corr(r, method="pearson")
        if pd.notna(corr) and math.isfinite(float(corr)):
            values.append(float(corr))
            dates.append(dt)
    return pd.Series(values, index=pd.Index(dates))


def _standard_t_stat(series: pd.Series) -> float:
    n = int(series.count())
    if n <= 1:
        return 0.0
    std = float(series.std(ddof=1))
    if not math.isfinite(std) or std <= 0:
        return 0.0
    return float(series.mean()) / (std / math.sqrt(n))


def _newey_west_t_stat(series: pd.Series, max_lag: int) -> float:
    values = series.dropna().astype(float).to_numpy()
    n = len(values)
    if n <= 1:
        return 0.0
    mean = float(values.mean())
    centered = values - mean
    gamma0 = float(np.dot(centered, centered) / n)
    variance = gamma0
    for lag in range(1, min(max_lag, n - 1) + 1):
        cov = float(np.dot(centered[lag:], centered[:-lag]) / n)
        weight = 1.0 - lag / (max_lag + 1.0)
        variance += 2.0 * weight * cov
    if not math.isfinite(variance) or variance <= 0:
        return 0.0
    return mean / math.sqrt(variance / n)


def compute_ic_metrics(
    factor: pd.DataFrame,
    forward_return: pd.DataFrame,
    *,
    horizon: int,
    valid_mask: pd.DataFrame,
    min_cross_section: int = 5,
) -> ICMetricSummary:
    ic = compute_ic_series_safe(
        factor,
        forward_return,
        valid_mask,
        min_cross_section=min_cross_section,
    )
    method = "standard" if horizon <= 1 else "newey_west"
    if ic.empty:
        return ICMetricSummary(
            horizon=horizon,
            rank_ic_mean=None,
            rank_ic_std=None,
            rank_icir=None,
            t_stat=None,
            t_stat_method=method,
            n_obs=0,
        )
    mean = float(ic.mean())
    std = float(ic.std(ddof=1)) if len(ic) > 1 else 0.0
    icir = mean / std if std > 0 else 0.0
    t_stat = (
        _standard_t_stat(ic)
        if method == "standard"
        else _newey_west_t_stat(ic, max_lag=max(1, horizon - 1))
    )
    return ICMetricSummary(
        horizon=horizon,
        rank_ic_mean=mean,
        rank_ic_std=std,
        rank_icir=icir,
        t_stat=t_stat,
        t_stat_method=method,
        n_obs=int(len(ic)),
    )
