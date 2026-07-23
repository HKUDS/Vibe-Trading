"""FMP daily gate must accept connector-style daily aliases like sina/tencent."""

from __future__ import annotations

from unittest.mock import patch

from backtest.loaders import fmp_loader as fl
from backtest.loaders.fmp_loader import DataLoader


def _body(symbol, bars):
    return {"symbol": symbol, "historical": bars}


_AAPL_BARS = [
    {"date": "2024-01-04", "open": 3.0, "high": 4.0, "low": 2.5, "close": 3.5, "volume": 200.0},
    {"date": "2024-01-03", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0},
]


def test_lowercase_1d_still_fetches(monkeypatch) -> None:
    """``1d`` used to hit the exact ``!= "1D"`` gate and return empty."""
    monkeypatch.setenv("FMP_API_KEY", "secret")
    with patch.object(fl, "throttled_get_json", return_value=_body("AAPL", _AAPL_BARS)) as mock_get:
        out = DataLoader().fetch(["AAPL.US"], "2024-01-01", "2024-01-31", interval="1d")
    assert set(out) == {"AAPL.US"}
    mock_get.assert_called_once()


def test_hour_interval_still_rejected(monkeypatch) -> None:
    monkeypatch.setenv("FMP_API_KEY", "secret")
    with patch.object(fl, "throttled_get_json") as mock_get:
        out = DataLoader().fetch(["AAPL.US"], "2024-01-01", "2024-01-31", interval="1H")
    assert out == {}
    mock_get.assert_not_called()
