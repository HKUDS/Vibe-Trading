# ============================================================
# 中文名称: 低贝塔溢价因子 (BAB)
# 简要说明: Frazzini-Pedersen低贝塔异象，做多低贝塔股票、做空高贝塔股票，横截面负贝塔排序。
# 典型用途: 捕获风险调整后低贝塔股票跑赢高贝塔股票的异象，风险平价类策略常用。
# ============================================================
"""academic Betting-Against-Beta (BAB): cross-sectional negative-beta ranking.

Reference:
    Frazzini, A., & Pedersen, L. H. (2014). "Betting against beta."
    Journal of Financial Economics, 111(1), 1-25.

BAB longs low-beta assets and shorts high-beta assets (both leverage-adjusted
in the original paper). We reproduce the core cross-sectional ranking signal
using only OHLCV inputs: rolling per-stock beta against an equal-weighted
market return (cross-sectional mean of daily returns), then rank stocks by
negative beta so low-beta names score highest. This differs from the
original construction, which uses a value-weighted market portfolio,
shrinkage-adjusted betas, and separate long-run correlation / short-run
volatility estimation windows (5y correlation, 1y volatility). We use a
single rolling window for both covariance and market variance, which is a
simplification.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import ts_cov, ts_std

__alpha_meta__ = {
    'id': 'academic_bab',
    'nickname': 'Frazzini-Pedersen 2014 betting-against-beta',
    'theme': ['volatility'],
    'formula_latex': r'\mathrm{zscore}_{x}\bigl(-\,\mathrm{ts\_cov}(r_i, r_m, 252) / \mathrm{ts\_std}(r_m, 252)^2\bigr)',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk'],
    'frequency': ['1d'],
    'decay_horizon': 252,
    'min_warmup_bars': 253,
    'notes': (
        'Frazzini & Pedersen (2014) BAB. Price-only proxy: market return is the '
        'cross-sectional mean of daily per-stock returns (equal-weighted, not '
        'value-weighted as in the original). Beta is Cov(r_i, r_m) / Var(r_m) '
        'over a single 252-day window (paper uses separate 1y vol / 5y '
        'correlation windows). Factor score is negative beta, cross-sectional '
        'z-scored so low-beta names rank highest, matching the long leg of the '
        'original long-short construction.'
    ),
}


def _cross_sectional_zscore(df: pd.DataFrame) -> pd.DataFrame:
    """Per-row z-score: (x - row_mean) / row_std; zero/NaN std rows -> NaN."""
    mean = df.mean(axis=1, skipna=True)
    std = df.std(axis=1, ddof=1, skipna=True)
    centered = df.sub(mean, axis=0)
    result = centered.div(std.where(std > 0), axis=0)
    return result.replace([np.inf, -np.inf], np.nan)


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return cross-sectional z-scored negative rolling beta (BAB long leg).

    Market return is the equal-weighted cross-sectional mean of per-stock
    daily returns, broadcast back to every column so ts_cov/ts_std (which
    operate per-column) see the same market series against each stock.
    """
    close = panel['close']
    returns = close.pct_change()

    market_ret = returns.mean(axis=1, skipna=True)
    market_df = pd.DataFrame(
        {col: market_ret for col in returns.columns},
        index=returns.index,
    )

    window = 252
    cov = ts_cov(returns, market_df, window)
    market_var = ts_std(market_df, window) ** 2
    beta = cov.div(market_var.where(market_var > 0))
    beta = beta.replace([np.inf, -np.inf], np.nan)

    return _cross_sectional_zscore(-beta)
