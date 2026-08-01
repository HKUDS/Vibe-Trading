"""Regression test for calc_metrics on equity curves with integer or non-datetime index.

Locks out a bug where calc_metrics raised AttributeError: 'int' object has no
attribute 'days' when bars_per_year=None (auto-detect mode) and equity_curve's
index was non-datetime (e.g. RangeIndex or Int64Index).
"""

import pandas as pd
from backtest.metrics import calc_metrics


def test_calc_metrics_auto_detect_bars_per_year_with_integer_index():
    """Prove calc_metrics auto-detect mode handles integer-indexed equity curves without crashing."""
    # Equity curve with RangeIndex(0, 5)
    equity_curve = pd.Series([100.0, 102.0, 105.0, 103.0, 108.0])
    
    # On un-fixed code, bars_per_year=None raises AttributeError: 'int' object has no attribute 'days'.
    # On fixed code, it returns a valid metrics dictionary.
    metrics = calc_metrics(equity_curve, trades=[], initial_cash=100.0, bars_per_year=None)
    
    assert isinstance(metrics, dict)
    assert "total_return" in metrics
    assert round(metrics["total_return"], 2) == 0.08
