# ============================================================
# 中文名称: 相关性重连因子 (Correlation Rewiring)
# 简要说明: 近期事件窗口与前置平静基线窗口的相关系数矩阵逐行平均绝对变化，衡量资产与市场整体关系的重构幅度；因子值取负（相关性结构稳定的资产得分高）。
# 典型用途: 风险/拥挤度横截面监控，慢性恶化(阴跌)资产识别；与波动率类因子互补的结构性风险视角。
# ============================================================
"""Correlation-rewiring score: how much an asset's correlation row changed.

Reference:
    The ``correlation-regime`` skill in this repository
    (``agent/src/skills/correlation-regime/SKILL.md``), Mode 4
    ("Correlation-Rewiring Leaderboard"). Streaming JVM reference
    implementation of the surrounding regime machinery:
    https://github.com/tarvyn-analytics/corrcalc-graphs-pipeline (Apache-2.0).

The skill's Mode 4 scores each asset by the row mean of |Δρ| between an
event-window correlation matrix and a calm-baseline correlation matrix:
assets whose relationship to the rest of the market rewired the most rank
highest. That formulation compares two analyst-chosen windows; this factor
is its causal rolling rendition for daily cross-sectional use: at each bar
the "event" window is the trailing ``event_window`` bars and the "calm"
baseline is the ``calm_window`` bars immediately preceding it (both strictly
trailing — no future data, no same-bar baseline).

The factor value is the cross-sectional z-score of the NEGATIVE rewiring
score, i.e. names with a stable correlation profile rank highest. This
direction encodes a stability-premium hypothesis (rapid rewiring flags
structural/crowding risk, the classic slow-bleed shape); it is a risk lens,
not a validated return predictor — see ``notes``.

Missing data: within each window, a column must have at least
``min_coverage`` of its bars observed, else its correlations (and score)
are NaN at that bar. Observed entries are demeaned per column and missing
entries contribute zero to the cross-products (a deterministic, causal
approximation of pairwise-complete correlation).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__alpha_meta__ = {
    "id": "academic_corr_rewire",
    "nickname": "correlation-rewiring stability score",
    "theme": ["volatility"],
    "formula_latex": (
        r"\mathrm{zscore}_{x}\Bigl(-\,\frac{1}{|J_i|}\sum_{j \in J_i}"
        r"\bigl|\rho_{ij}^{\mathrm{event}} - \rho_{ij}^{\mathrm{calm}}\bigr|\Bigr),"
        r"\quad \rho^{\mathrm{event}} = \mathrm{corr}(r_{t-19..t}),\ "
        r"\rho^{\mathrm{calm}} = \mathrm{corr}(r_{t-139..t-20})"
    ),
    "columns_required": ["close"],
    "universe": ["equity_us", "equity_cn", "equity_hk", "crypto"],
    "frequency": ["1d"],
    "decay_horizon": 60,
    "min_warmup_bars": 142,
    "notes": (
        "Causal rolling rendition of the correlation-regime skill's Mode 4 "
        "(rewiring leaderboard): per-asset row mean of |corr(event) - "
        "corr(calm)| where the event window is the trailing 20 bars and the "
        "calm baseline is the 120 bars immediately before it, sign-flipped "
        "and cross-sectionally z-scored so correlation-stable names rank "
        "highest. Framed as a structural risk / crowding lens, not a "
        "validated alpha: the author's public validation of the underlying "
        "regime machinery covers regime detection and attribution on "
        "historical replays only and makes no return-prediction claim for "
        "this cross-sectional form. Missing data: columns need >= 90% "
        "in-window coverage, else NaN; observed entries are demeaned and "
        "missing entries contribute zero to the correlation cross-products."
    ),
}


def _window_corr(window: np.ndarray, min_obs: int) -> np.ndarray:
    """NaN-aware correlation matrix of one trailing window.

    Args:
        window: Array of shape (bars, n_assets) of returns, may contain NaN.
        min_obs: Minimum observed bars a column needs; below it the column's
            row/column in the result is NaN.

    Returns:
        (n_assets, n_assets) correlation matrix. Columns with insufficient
        coverage or zero variance are NaN.
    """
    observed = np.isfinite(window)
    n_obs = observed.sum(axis=0)
    enough = n_obs >= min_obs

    filled = np.where(observed, window, 0.0)
    col_mean = filled.sum(axis=0) / np.maximum(n_obs, 1)
    centered = np.where(observed, window - col_mean, 0.0)
    norm = np.sqrt((centered * centered).sum(axis=0))
    scaled = centered / np.where(norm > 0.0, norm, np.nan)

    corr = scaled.T @ scaled
    corr[~enough, :] = np.nan
    corr[:, ~enough] = np.nan
    return corr


def _rewiring_scores(
    returns: np.ndarray,
    event_window: int,
    calm_window: int,
    min_coverage: float,
    min_peers: int,
) -> np.ndarray:
    """Rolling per-bar, per-asset rewiring scores (row means of |Δρ|).

    Args:
        returns: (n_bars, n_assets) return matrix, may contain NaN.
        event_window: Trailing bars forming the event correlation matrix.
        calm_window: Bars immediately preceding the event window forming the
            calm-baseline correlation matrix.
        min_coverage: Required fraction of observed bars per column, per window.
        min_peers: Minimum finite |Δρ| entries a row needs for a score.

    Returns:
        (n_bars, n_assets) array of rewiring scores (NaN during warmup and
        wherever coverage is insufficient).
    """
    n_bars, n_assets = returns.shape
    scores = np.full((n_bars, n_assets), np.nan)
    warmup = calm_window + event_window
    min_obs_event = int(np.ceil(min_coverage * event_window))
    min_obs_calm = int(np.ceil(min_coverage * calm_window))
    diag = np.arange(n_assets)

    for t in range(warmup - 1, n_bars):
        # Both windows trail bar t. Worked example with event=20, calm=120 at
        # t=139: event = rows 120..139 (the 20 bars up to and including t),
        # calm = rows 0..119 (the 120 bars immediately before the event
        # window). Nothing after row t is ever touched.
        event = returns[t - event_window + 1 : t + 1]
        calm = returns[t - warmup + 1 : t - event_window + 1]
        delta = np.abs(_window_corr(event, min_obs_event) - _window_corr(calm, min_obs_calm))
        delta[diag, diag] = np.nan
        finite = np.isfinite(delta)
        n_finite = finite.sum(axis=1)
        row_sum = np.where(finite, delta, 0.0).sum(axis=1)
        with np.errstate(invalid="ignore"):
            row_mean = row_sum / np.where(n_finite >= min_peers, n_finite, np.nan)
        scores[t] = row_mean
    return scores


def _cross_sectional_zscore(df: pd.DataFrame) -> pd.DataFrame:
    """Per-row z-score: (x - row_mean) / row_std; zero/NaN std rows -> NaN."""
    mean = df.mean(axis=1, skipna=True)
    std = df.std(axis=1, ddof=1, skipna=True)
    centered = df.sub(mean, axis=0)
    result = centered.div(std.where(std > 0), axis=0)
    return result.replace([np.inf, -np.inf], np.nan)


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return the cross-sectional z-scored negative correlation-rewiring score.

    At each bar, each asset's rewiring score is the mean over peers of the
    absolute change in pairwise correlation between the trailing 20-bar event
    window and the 120-bar calm baseline immediately preceding it. The factor
    is the z-scored negative score: correlation-stable names rank highest.

    Args:
        panel: Wide OHLCV panel; only ``close`` is used.

    Returns:
        DataFrame shaped like ``panel['close']`` with the factor values.
    """
    close = panel["close"]
    # fill_method=None: a missing price must yield a missing return (pandas 2.x
    # would otherwise forward-fill and defeat the coverage guard). Matches the
    # bench's own forward-return convention.
    returns = close.pct_change(fill_method=None)

    scores = _rewiring_scores(
        returns.to_numpy(dtype=float),
        event_window=20,
        calm_window=120,
        min_coverage=0.9,
        min_peers=2,
    )
    rewiring = pd.DataFrame(scores, index=close.index, columns=close.columns)
    return _cross_sectional_zscore(-rewiring)
