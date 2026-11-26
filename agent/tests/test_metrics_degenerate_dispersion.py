"""Risk ratios must not fabricate a huge value when there is no dispersion.

A one-bar return series (``std`` undefined, n=1) or a perfectly constant
return path (``std`` ~ 0, including float-error dust) carries no dispersion to
annualise. The ``vol + 1e-10`` guard turned that undefined denominator into a
finite epsilon, so a run card could rank a flat/constant strategy as a
Sharpe-1.6-billion strategy. Degenerate dispersion must report the existing
``0.0`` sentinel instead, while genuine (if small) dispersion keeps its ratio.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from backtest.metrics import calc_metrics


def _metrics_from_returns(returns, initial_cash=100.0):
    """Build an equity curve whose per-bar returns equal ``returns`` exactly."""
    returns = pd.Series(returns, index=pd.bdate_range("2025-01-01", periods=len(returns)))
    equity = initial_cash * (1.0 + returns).cumprod()
    return equity, returns


def test_single_bar_nonzero_return_sharpe_is_undefined_sentinel() -> None:
    eq = pd.Series([101.0], index=pd.bdate_range("2025-01-01", periods=1))

    m = calc_metrics(eq, [], 100.0, bars_per_year=252)

    assert math.isfinite(m["sharpe"])
    assert m["sharpe"] == 0.0


def test_single_bar_nonzero_return_information_ratio_is_undefined_sentinel() -> None:
    eq = pd.Series([101.0], index=pd.bdate_range("2025-01-01", periods=1))
    bench = pd.Series([0.0], index=eq.index)

    m = calc_metrics(eq, [], 100.0, bars_per_year=252, bench_ret=bench)

    assert math.isfinite(m["information_ratio"])
    assert m["information_ratio"] == 0.0


def test_constant_return_path_sharpe_is_undefined_sentinel() -> None:
    # Every bar compounds at exactly 10%; only float error separates the
    # returns, so std() is ~1e-16 rather than exactly zero.
    equity, returns = _metrics_from_returns([0.10, 0.10, 0.10])
    assert float(returns.std()) < 1e-12

    m = calc_metrics(equity, [], 100.0, bars_per_year=252)

    assert math.isfinite(m["sharpe"])
    assert m["sharpe"] == 0.0


def test_constant_return_path_information_ratio_is_undefined_sentinel() -> None:
    equity, _ = _metrics_from_returns([0.10, 0.10, 0.10])
    bench = pd.Series(0.0, index=equity.index)

    m = calc_metrics(equity, [], 100.0, bars_per_year=252, bench_ret=bench)

    assert math.isfinite(m["information_ratio"])
    assert m["information_ratio"] == 0.0


def test_genuine_small_dispersion_keeps_the_ratio() -> None:
    # Mean 1e-5 with a real +/-1e-6 oscillation: tiny, but not degenerate.
    returns = 1e-5 + 1e-6 * np.array([1.0, -1.0] * 20)
    equity, returns = _metrics_from_returns(returns)

    m = calc_metrics(equity, [], 100.0, bars_per_year=252, bench_ret=pd.Series(0.0, index=equity.index))

    assert float(returns.std()) > 1e-12
    assert math.isfinite(m["sharpe"])
    assert m["sharpe"] > 0.0
    assert math.isfinite(m["information_ratio"])
    assert m["information_ratio"] > 0.0
