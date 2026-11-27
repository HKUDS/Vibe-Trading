"""Validation uses the metrics sentinel when return dispersion is undefined."""

import numpy as np
import pandas as pd
import pytest

from backtest.metrics import calc_metrics
from backtest.models import TradeRecord
from backtest.validation import _sharpe, run_validation


@pytest.mark.parametrize("rate", [0.01, -0.01, 0.0])
def test_constant_returns_do_not_create_billion_scale_validation_sharpes(rate):
    initial = 100.0
    dates = pd.date_range("2026-01-01", periods=12)
    equity = pd.Series(initial * (1 + rate) ** np.arange(1, 13), index=dates)
    pnls = np.diff(np.r_[initial, equity.to_numpy()])
    trades = [
        TradeRecord(
            symbol="TEST", direction=1, entry_price=100.0, exit_price=100.0,
            entry_time=dates[i], exit_time=dates[i], size=1.0, leverage=1.0,
            pnl=float(pnl), pnl_pct=rate * 100, exit_reason="signal",
            holding_bars=1, commission=0.0,
        )
        for i, pnl in enumerate(pnls)
    ]
    results = run_validation(
        {"validation": {
            "bootstrap": {"n_bootstrap": 30},
            "walk_forward": {"n_windows": 2},
            "monte_carlo": {"n_simulations": 30},
        }}, equity, trades, initial,
    )
    assert calc_metrics(equity, trades, initial)["sharpe"] == 0.0
    bootstrap = results["bootstrap"]
    assert bootstrap["observed_sharpe"] == 0.0
    assert bootstrap["ci_lower"] == bootstrap["ci_upper"] == 0.0
    assert bootstrap["sharpe_samples"] == [0.0] * 30
    assert [window["sharpe"] for window in results["walk_forward"]["windows"]] == [0.0, 0.0]
    assert results["monte_carlo"]["actual_sharpe"] == 0.0


def test_real_small_dispersion_keeps_the_unbiased_ratio():
    returns = np.array([1e-5 - 1e-6, 1e-5 + 1e-6] * 5)
    expected = returns.mean() / returns.std() * np.sqrt(252)
    assert _sharpe(returns) == pytest.approx(expected, rel=1e-10)
