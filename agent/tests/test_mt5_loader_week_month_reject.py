"""MT5 loader must map week/month tokens and never rewrite unknown intervals to daily."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backtest.loaders.mt5_loader import DataLoader, _INTERVAL_MAP


def test_week_and_month_tokens_map_like_connector() -> None:
    assert _INTERVAL_MAP["1W"] == "TIMEFRAME_W1"
    assert _INTERVAL_MAP["1w"] == "TIMEFRAME_W1"
    assert _INTERVAL_MAP["1M"] == "TIMEFRAME_MN1"
    assert _INTERVAL_MAP["1m"] == "TIMEFRAME_M1"


def test_unsupported_interval_returns_empty_without_daily_rewrite() -> None:
    """``2H`` used to fall back to TIMEFRAME_D1 and fetch day bars."""
    with patch.object(DataLoader, "_fetch_one") as mock_fetch:
        out = DataLoader().fetch(
            ["EURUSD"], "2024-01-01", "2024-01-31", interval="2H"
        )
    assert out == {}
    mock_fetch.assert_not_called()


def test_week_interval_uses_w1_not_daily() -> None:
    frame = MagicMock()
    frame.empty = False
    with patch(
        "backtest.loaders.mt5_loader.cached_loader_fetch", return_value=frame
    ) as mock_cache:
        out = DataLoader().fetch(
            ["EURUSD"], "2024-01-01", "2024-01-31", interval="1W"
        )
    assert set(out) == {"EURUSD"}
    assert mock_cache.call_args.kwargs["timeframe"] == "1W"
