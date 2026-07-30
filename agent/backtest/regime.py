"""Correlation-regime timeline: edge density + hysteresis over time.

Implements Mode 1 of the ``correlation-regime`` skill on top of the same
price data the /correlation endpoint uses: rolling pairwise correlations are
reduced to an edge-density scalar per bar, the density series is smoothed
with a trailing (causal) window, and a two-threshold hysteresis state
machine labels each bar FUSED or not. Used by the /correlation/regime API
endpoint. Descriptive risk context — not a trading signal.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

from backtest.correlation import _close_series, _fetch_price_series

logger = logging.getLogger(__name__)


def compute_edge_density(
    returns: pd.DataFrame,
    corr_window: int = 60,
    edge_threshold: float = 0.5,
) -> pd.Series:
    """Reduce rolling correlation matrices to an edge-density series.

    Edge density is the fraction of distinct asset pairs whose rolling
    |correlation| clears ``edge_threshold`` — a scalar "how fused is the
    market" gauge in [0, 1].

    Args:
        returns: Multi-asset return matrix, columns are symbols
        corr_window: Rolling window length (bars) for pairwise correlation
        edge_threshold: |ρ| level at which a pair counts as an "edge"

    Returns:
        Edge-density series aligned to ``returns.index`` (NaN during warmup)
    """
    n_assets = returns.shape[1]
    n_pairs = n_assets * (n_assets - 1) // 2
    if n_pairs == 0:
        return pd.Series(np.nan, index=returns.index)
    upper_mask = np.triu(np.ones((n_assets, n_assets), dtype=bool), k=1)

    density = pd.Series(np.nan, index=returns.index)
    for i in range(corr_window, len(returns) + 1):
        corr = returns.iloc[i - corr_window:i].corr().abs().to_numpy()
        density.iloc[i - 1] = float((corr[upper_mask] >= edge_threshold).sum()) / n_pairs
    return density


def detect_regimes(
    density: pd.Series,
    smooth_window: int = 5,
    enter_threshold: float = 0.65,
    exit_threshold: float = 0.45,
) -> pd.DataFrame:
    """Hysteresis (Schmitt-trigger) regime state machine on smoothed density.

    The market is FUSED once smoothed density reaches ``enter_threshold`` and
    stays FUSED until it falls back to ``exit_threshold``. The dead band
    between the two thresholds is what suppresses chatter.

    Args:
        density: Edge-density series from :func:`compute_edge_density`
        smooth_window: Trailing smoothing window (causal; never centered)
        enter_threshold: Density level that opens a FUSED regime
        exit_threshold: Density level that closes it (must be < enter_threshold)

    Returns:
        DataFrame with columns ``density``, ``smoothed``, ``fused`` (0/1)
    """
    if exit_threshold >= enter_threshold:
        raise ValueError("exit_threshold must be below enter_threshold")

    # Trailing mean = causal. A centered window here silently reads the future.
    smoothed = density.rolling(smooth_window, min_periods=1).mean()

    fused = False
    states = np.zeros(len(smoothed), dtype=int)
    for i, value in enumerate(smoothed.to_numpy()):
        if np.isnan(value):
            states[i] = int(fused)
            continue
        if not fused and value >= enter_threshold:
            fused = True
        elif fused and value <= exit_threshold:
            fused = False
        states[i] = int(fused)

    return pd.DataFrame(
        {"density": density, "smoothed": smoothed, "fused": states},
        index=density.index,
    )


def _aligned_returns(price_series: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build a date-aligned daily-returns frame (one column per code).

    Mirrors the alignment in ``_rolling_correlation_matrix``: indexes are
    normalized to midnight so cross-market assets (e.g. crypto at UTC
    midnight vs US equity at EDT midnight) share dates, then inner-joined.
    ``fill_method=None`` is explicit because under the project's
    pandas>=2,<3 pin the ``pct_change`` default forward-fills missing
    prices, silently manufacturing 0% returns.
    """
    returns_frames = []
    for code in sorted(price_series):
        ts = _close_series(code, price_series[code])
        ts.index = ts.index.normalize()
        rets = ts.pct_change(fill_method=None).dropna()
        rets.name = code
        returns_frames.append(rets)

    aligned = pd.concat(returns_frames, axis=1).dropna()
    if aligned.empty:
        raise ValueError("No overlapping return data between assets")
    return aligned


def _fused_episodes(dates: list[str], fused: list[int]) -> list[Dict[str, Optional[str]]]:
    """Contiguous FUSED intervals within the returned window.

    ``end`` is the last date observed FUSED, or None while the final bar is
    still FUSED (episode ongoing).
    """
    episodes: list[Dict[str, Optional[str]]] = []
    start: Optional[str] = None
    last_fused: Optional[str] = None
    for date, state in zip(dates, fused):
        if state:
            if start is None:
                start = date
            last_fused = date
        elif start is not None:
            episodes.append({"start": start, "end": last_fused})
            start = None
    if start is not None:
        episodes.append({"start": start, "end": None})
    return episodes


def compute_regime_timeline(
    codes: list[str],
    days: int = 90,
    corr_window: int = 60,
    edge_threshold: float = 0.5,
    smooth_window: int = 5,
    enter_threshold: float = 0.65,
    exit_threshold: float = 0.45,
) -> Dict[str, object]:
    """Fetch price data and compute the correlation-regime timeline.

    Args:
        codes: List of asset codes, as for :func:`compute_correlation_matrix`.
        days: Number of trailing timeline bars to return.
        corr_window: Rolling window (bars) for pairwise correlation.
        edge_threshold: |ρ| level at which a pair counts as an "edge".
        smooth_window: Trailing smoothing window (bars) for the density series.
        enter_threshold: Smoothed density that opens a FUSED regime.
        exit_threshold: Smoothed density that closes it (must be below
            ``enter_threshold``).

    Returns:
        Dict with keys: labels, dates, density, smoothed, fused, episodes,
        params. ``density``/``smoothed`` use None for warmup bars; ``fused``
        is 0/1 per bar; ``episodes`` lists FUSED intervals with ``end=None``
        while the final bar is still FUSED.
    """
    from datetime import datetime, timedelta

    if exit_threshold >= enter_threshold:
        raise ValueError("exit_threshold must be below enter_threshold")

    # Each returned bar needs a full corr_window of history behind it, so the
    # warmup falls outside the returned window: extend /correlation's +60
    # calendar-day fetch buffer by the correlation window (and a margin for
    # non-trading days).
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (
        datetime.now() - timedelta(days=days + corr_window + 90)
    ).strftime("%Y-%m-%d")

    price_series = _fetch_price_series(codes, start_date, end_date)

    if len(price_series) < 2:
        raise ValueError(
            f"Could not fetch price data for at least 2 assets. "
            f"Fetched: {list(price_series.keys())}"
        )

    returns = _aligned_returns(price_series)
    density = compute_edge_density(
        returns, corr_window=corr_window, edge_threshold=edge_threshold
    )
    regimes = detect_regimes(
        density,
        smooth_window=smooth_window,
        enter_threshold=enter_threshold,
        exit_threshold=exit_threshold,
    )
    # Trim to the requested window only after the state machine has run, so
    # the regime state at the window's first bar reflects the full history.
    if len(regimes) > days:
        regimes = regimes.iloc[-days:]

    dates = [d.strftime("%Y-%m-%d") for d in regimes.index]
    density_out = [
        None if np.isnan(v) else round(float(v), 4) for v in regimes["density"]
    ]
    smoothed_out = [
        None if np.isnan(v) else round(float(v), 4) for v in regimes["smoothed"]
    ]
    fused_out = [int(v) for v in regimes["fused"]]

    return {
        "labels": list(returns.columns),
        "dates": dates,
        "density": density_out,
        "smoothed": smoothed_out,
        "fused": fused_out,
        "episodes": _fused_episodes(dates, fused_out),
        "params": {
            "days": days,
            "corr_window": corr_window,
            "edge_threshold": edge_threshold,
            "smooth_window": smooth_window,
            "enter_threshold": enter_threshold,
            "exit_threshold": exit_threshold,
        },
    }
