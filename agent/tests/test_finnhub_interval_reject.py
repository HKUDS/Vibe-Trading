"""Finnhub must reject non-daily intervals instead of silently returning day bars."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backtest.loaders import finnhub_loader as fh


def test_unsupported_interval_does_not_hit_api() -> None:
    """Runner ``1H`` must not fall through to Finnhub resolution=D."""
    with patch.object(fh, "throttled_get_json") as mock_get:
        with patch("src.config.accessor.get_env_config") as cfg:
            c = MagicMock()
            c.data.finnhub_api_key = "KEY"
            cfg.return_value = c
            out = fh.DataLoader().fetch(
                ["AAPL"], "2024-01-01", "2024-01-31", interval="1H"
            )
    assert out == {}
    mock_get.assert_not_called()


def test_four_hour_interval_also_rejected() -> None:
    with patch.object(fh, "throttled_get_json") as mock_get:
        with patch("src.config.accessor.get_env_config") as cfg:
            c = MagicMock()
            c.data.finnhub_api_key = "KEY"
            cfg.return_value = c
            out = fh.DataLoader().fetch(
                ["AAPL"], "2024-01-01", "2024-01-31", interval="4H"
            )
    assert out == {}
    mock_get.assert_not_called()


def test_daily_interval_still_fetches() -> None:
    payload = {
        "s": "ok",
        "t": [1704067200],
        "o": [100.0],
        "h": [110.0],
        "l": [99.0],
        "c": [105.0],
        "v": [1000],
    }
    with patch.object(fh, "throttled_get_json", return_value=payload) as mock_get:
        with patch("src.config.accessor.get_env_config") as cfg:
            c = MagicMock()
            c.data.finnhub_api_key = "KEY"
            cfg.return_value = c
            out = fh.DataLoader().fetch(
                ["AAPL"], "2024-01-01", "2024-01-31", interval="1D"
            )
    assert "AAPL" in out
    mock_get.assert_called_once()
