"""Tiingo must reject non-daily intervals instead of silently returning day bars."""

from __future__ import annotations

from unittest.mock import patch

from backtest.loaders import tiingo_loader as tg


def test_unsupported_interval_does_not_hit_api() -> None:
    """Runner ``1H`` must not fall through to Tiingo daily EOD."""
    with patch.object(tg, "throttled_get_json") as mock_get:
        with patch.object(tg, "_resolve_key", return_value="KEY"):
            out = tg.DataLoader().fetch(
                ["AAPL"], "2024-01-01", "2024-01-31", interval="1H"
            )
    assert out == {}
    mock_get.assert_not_called()


def test_four_hour_interval_also_rejected() -> None:
    with patch.object(tg, "throttled_get_json") as mock_get:
        with patch.object(tg, "_resolve_key", return_value="KEY"):
            out = tg.DataLoader().fetch(
                ["AAPL"], "2024-01-01", "2024-01-31", interval="4H"
            )
    assert out == {}
    mock_get.assert_not_called()


def test_daily_interval_still_fetches() -> None:
    payload = [
        {
            "date": "2024-01-02T00:00:00.000Z",
            "open": 100,
            "high": 110,
            "low": 99,
            "close": 105,
            "volume": 1000,
        }
    ]
    with patch.object(tg, "throttled_get_json", return_value=payload) as mock_get:
        with patch.object(tg, "_resolve_key", return_value="KEY"):
            out = tg.DataLoader().fetch(
                ["AAPL"], "2024-01-01", "2024-01-31", interval="1D"
            )
    assert "AAPL" in out
    mock_get.assert_called_once()
