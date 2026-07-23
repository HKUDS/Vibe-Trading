"""Alpha Vantage must reject non-daily intervals instead of silently returning day bars."""

from __future__ import annotations

from unittest.mock import patch

from backtest.loaders import alphavantage_loader as av


def test_unsupported_interval_does_not_hit_api(monkeypatch) -> None:
    """Runner ``1H`` must not fall through to TIME_SERIES_DAILY."""
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "ABC123")
    with patch.object(av, "throttled_get_json") as mock_get:
        out = av.DataLoader().fetch(["AAPL"], "2024-01-01", "2024-01-31", interval="1H")
    assert out == {}
    mock_get.assert_not_called()


def test_four_hour_interval_also_rejected(monkeypatch) -> None:
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "ABC123")
    with patch.object(av, "throttled_get_json") as mock_get:
        out = av.DataLoader().fetch(["AAPL"], "2024-01-01", "2024-01-31", interval="4H")
    assert out == {}
    mock_get.assert_not_called()


def test_daily_interval_still_fetches(monkeypatch) -> None:
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "ABC123")
    payload = {
        "Time Series (Daily)": {
            "2024-01-02": {
                "1. open": "100",
                "2. high": "110",
                "3. low": "99",
                "4. close": "105",
                "5. volume": "1000",
            }
        }
    }
    with patch.object(av, "throttled_get_json", return_value=payload) as mock_get:
        out = av.DataLoader().fetch(["AAPL"], "2024-01-01", "2024-01-31", interval="1D")
    assert "AAPL" in out
    mock_get.assert_called_once()
