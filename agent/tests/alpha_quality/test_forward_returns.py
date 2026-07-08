from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.alpha_quality.forward_returns import compute_forward_return


def test_forward_return_uses_execution_lag() -> None:
    idx = pd.date_range("2020-01-01", periods=4, freq="D")
    close = pd.DataFrame({"AAA": [100.0, 110.0, 121.0, 133.1]}, index=idx)

    result = compute_forward_return(close, horizon=1, execution_lag=1)

    expected = close.loc[idx[2], "AAA"] / close.loc[idx[1], "AAA"] - 1.0
    assert result.loc[idx[0], "AAA"] == pytest.approx(expected)


def test_forward_return_horizon_two_uses_trading_rows_not_same_bar() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="D")
    close = pd.DataFrame({"AAA": [100.0, 105.0, 110.25, 121.275, 133.4025]}, index=idx)

    result = compute_forward_return(close, horizon=2, execution_lag=1)

    expected = close.loc[idx[3], "AAA"] / close.loc[idx[1], "AAA"] - 1.0
    assert result.loc[idx[0], "AAA"] == pytest.approx(expected)


@pytest.mark.parametrize(
    ("horizon", "execution_lag", "message"),
    [(0, 1, "horizon must be >= 1"), (1, 0, "execution_lag must be >= 1")],
)
def test_forward_return_rejects_lookahead_parameters(
    horizon: int, execution_lag: int, message: str
) -> None:
    close = pd.DataFrame({"AAA": [1.0, 2.0, 3.0]})

    with pytest.raises(ValueError, match=message):
        compute_forward_return(close, horizon=horizon, execution_lag=execution_lag)


def test_forward_return_replaces_infinite_values_with_nan() -> None:
    close = pd.DataFrame({"AAA": [1.0, 0.0, 2.0, 4.0]})

    result = compute_forward_return(close, horizon=1, execution_lag=1)

    assert np.isnan(result.iloc[0, 0])
