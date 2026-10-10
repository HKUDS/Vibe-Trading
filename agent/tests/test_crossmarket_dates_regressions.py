import pandas as pd
import pytest
from backtest.correlation import compute_correlation_matrix
from backtest.regime import compute_regime_timeline


def _prices(tz):
    return pd.DataFrame(
        {"close": [100, 105, 101, 109, 107]},
        index=pd.date_range("2025-01-01", periods=5, tz=tz),
    )


@pytest.mark.parametrize("tz", ["America/New_York", None])
def test_correlation_aligns_local_calendar_dates_across_timezones(monkeypatch, tz):
    prices = {"A": _prices("UTC"), "B": _prices(tz)}
    monkeypatch.setattr(
        "backtest.correlation._fetch_price_series", lambda *args: prices
    )
    actual = compute_correlation_matrix(["A", "B"], days=30)
    assert actual["matrix"] == [[1.0, 1.0], [1.0, 1.0]]


def test_regime_uses_same_calendar_alignment(monkeypatch):
    prices = {"A": _prices("UTC"), "B": _prices("America/New_York")}
    monkeypatch.setattr("backtest.regime._fetch_price_series", lambda *args: prices)
    actual = compute_regime_timeline(["A", "B"], corr_window=2, smooth_window=1)
    assert actual["dates"] == ["2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05"]
    assert actual["density"] == [None, 1.0, 1.0, 1.0]
