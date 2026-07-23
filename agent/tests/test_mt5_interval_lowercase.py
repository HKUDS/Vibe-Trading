"""MT5 loader must accept trading-convention lowercase 1h/4h/1d intervals."""

from __future__ import annotations

from backtest.loaders.mt5_loader import _INTERVAL_MAP


def test_lowercase_hour_day_aliases_match_project_tokens() -> None:
    assert _INTERVAL_MAP["1h"] == "TIMEFRAME_H1"
    assert _INTERVAL_MAP["1H"] == "TIMEFRAME_H1"
    assert _INTERVAL_MAP["4h"] == "TIMEFRAME_H4"
    assert _INTERVAL_MAP["4H"] == "TIMEFRAME_H4"
    assert _INTERVAL_MAP["1d"] == "TIMEFRAME_D1"
    assert _INTERVAL_MAP["1D"] == "TIMEFRAME_D1"
