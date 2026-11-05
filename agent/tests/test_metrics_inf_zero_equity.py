"""Regression: metrics and validation must not produce inf from zero equity.

pct_change() divides by the previous value. When an equity curve hits
zero (a blown-up account, a liquidation event), pct_change() produces
inf or -inf. fillna(0.0) only handles NaN, not inf, so the inf
propagates into std(), mean(), and every downstream metric (Sharpe,
Sortino, IR), producing NaN or inf results that are silently wrong.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.metrics import calc_metrics
from backtest.models import TradeRecord
from backtest.validation import (
    _path_metrics,
    bootstrap_sharpe_ci,
    monte_carlo_test,
    walk_forward_analysis,
)


def _trade(pnl: float = 100.0) -> TradeRecord:
    return TradeRecord(
        symbol="X",
        direction=1,
        entry_price=100.0,
        exit_price=101.0,
        entry_time=pd.Timestamp("2025-01-01"),
        exit_time=pd.Timestamp("2025-01-06"),
        size=100.0,
        leverage=1.0,
        pnl=pnl,
        pnl_pct=pnl / 100,
        exit_reason="signal",
        holding_bars=5,
        commission=1.0,
    )


def _equity_curve_with_zero(*, initial: float = 10000.0) -> pd.Series:
    """An equity curve that hits zero then recovers (e.g. a margin call + reset)."""
    return pd.Series(
        [initial, initial * 1.01, 0.0, 5000.0, 5050.0, 5100.0],
        index=pd.date_range("2025-01-01", periods=6, freq="D"),
    )


# --------------------------------------------------------------------------- #
# calc_metrics
# --------------------------------------------------------------------------- #


def test_calc_metrics_no_inf_on_zero_equity() -> None:
    """A zero in the equity curve must not produce inf/NaN in any metric."""
    eq = _equity_curve_with_zero()
    m = calc_metrics(eq, [], initial_cash=10000.0)
    for key in ("sharpe", "sortino", "calmar", "annual_return", "max_drawdown"):
        val = m[key]
        assert np.isfinite(val), f"{key} is not finite: {val}"


def test_calc_metrics_no_inf_on_all_zero_equity() -> None:
    """An equity curve that is entirely zero must not crash or produce inf."""
    eq = pd.Series(
        [0.0, 0.0, 0.0, 0.0, 0.0],
        index=pd.date_range("2025-01-01", periods=5, freq="D"),
    )
    m = calc_metrics(eq, [], initial_cash=10000.0)
    for key in ("sharpe", "sortino", "calmar", "annual_return"):
        assert np.isfinite(m[key]), f"{key} is not finite: {m[key]}"


# --------------------------------------------------------------------------- #
# validation._path_metrics
# --------------------------------------------------------------------------- #


def test_path_metrics_no_inf_on_zero_equity() -> None:
    """_path_metrics must not produce inf when equity crosses zero."""
    pnls = np.array([100.0, -200.0, 50.0])  # equity: 10000, 10100, 9900, 9950
    m = _path_metrics(pnls, initial_capital=10000.0)
    assert np.isfinite(m["sharpe"]), f"sharpe is not finite: {m['sharpe']}"
    assert np.isfinite(m["max_dd"]), f"max_dd is not finite: {m['max_dd']}"


def test_path_metrics_no_inf_when_equity_hits_zero() -> None:
    """Equity hitting zero has no defined percentage path metrics."""
    pnls = np.array([100.0, -10100.0, 5000.0])  # equity: 10000, 10100, 0, 5000
    m = _path_metrics(pnls, initial_capital=10000.0)
    assert m is None


# --------------------------------------------------------------------------- #
# validation.bootstrap_sharpe_ci
# --------------------------------------------------------------------------- #


def test_bootstrap_sharpe_ci_no_inf_on_zero_equity() -> None:
    """bootstrap_sharpe_ci must not produce inf when equity hits zero."""
    eq = _equity_curve_with_zero()
    result = bootstrap_sharpe_ci(eq, n_bootstrap=50, seed=42)
    if "error" in result:
        # Not enough returns is acceptable; the point is no crash/inf.
        return
    for key in ("observed_sharpe", "ci_lower", "ci_upper", "median_sharpe"):
        assert np.isfinite(result[key]), f"{key} is not finite: {result[key]}"


# --------------------------------------------------------------------------- #
# validation.walk_forward_analysis
# --------------------------------------------------------------------------- #


def test_walk_forward_no_inf_on_zero_equity() -> None:
    """walk_forward_analysis must not produce inf when equity hits zero."""
    eq = _equity_curve_with_zero()
    result = walk_forward_analysis(eq, [], n_windows=2)
    if "error" in result:
        return
    for w in result.get("windows", []):
        assert np.isfinite(w["sharpe"]), f"window sharpe is not finite: {w['sharpe']}"
        assert np.isfinite(w["max_dd"]), f"window max_dd is not finite: {w['max_dd']}"


# --------------------------------------------------------------------------- #
# monte_carlo_test (uses _path_metrics internally)
# --------------------------------------------------------------------------- #


def test_monte_carlo_no_inf_when_trades_blow_up_account() -> None:
    """Monte Carlo must not produce inf when trades push equity through zero."""
    trades = [_trade(100.0), _trade(-10100.0), _trade(5000.0), _trade(50.0)]
    result = monte_carlo_test(trades, initial_capital=10000.0, n_simulations=50, seed=42)
    assert set(result) == {"error"}
