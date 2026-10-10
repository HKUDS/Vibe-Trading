import numpy as np
import pandas as pd
import pytest
from backtest.risk_xray import compute_risk_xray


def test_risk_xray_returns_do_not_bridge_missing_prices():
    closes = pd.DataFrame(
        {
            "a": [100.0, 110.0, np.nan, 120.0, 132.0, 125.0],
            "b": [100.0, 105.0, 107.0, 109.0, 112.0, 115.0],
        },
        index=pd.date_range("2025-01-01", periods=6),
    )
    observed = closes.pct_change(fill_method=None).dropna()
    portfolio = observed.mean(axis=1)
    actual = compute_risk_xray(closes, {"a": 0.5, "b": 0.5}, min_history=2)
    assert actual["inputs"]["return_observations"] == len(observed)
    assert actual["volatility"]["daily_vol"] == pytest.approx(portfolio.std(ddof=1))


def test_risk_xray_refuses_prices_with_no_adjacent_shared_returns():
    closes = pd.DataFrame(
        {"a": [100.0, np.nan, 110.0, np.nan, 120.0]},
        index=pd.date_range("2025-01-01", periods=5),
    )
    with pytest.raises(ValueError, match="no overlapping return"):
        compute_risk_xray(closes, {"a": 1.0}, min_history=2)
