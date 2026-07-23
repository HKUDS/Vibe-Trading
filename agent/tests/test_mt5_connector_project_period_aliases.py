"""MT5 connector must map project-style 1H/4H/1D periods to hour/day bars."""

from __future__ import annotations

from src.trading.connectors.mt5.reads import _TIMEFRAME_MAP


def test_timeframe_map_accepts_project_hour_day_tokens() -> None:
    assert _TIMEFRAME_MAP["1H"] == "TIMEFRAME_H1"
    assert _TIMEFRAME_MAP["1h"] == "TIMEFRAME_H1"
    assert _TIMEFRAME_MAP["4H"] == "TIMEFRAME_H4"
    assert _TIMEFRAME_MAP["4h"] == "TIMEFRAME_H4"
    assert _TIMEFRAME_MAP["1D"] == "TIMEFRAME_D1"
    assert _TIMEFRAME_MAP["1d"] == "TIMEFRAME_D1"
    assert _TIMEFRAME_MAP["1W"] == "TIMEFRAME_W1"
    assert _TIMEFRAME_MAP["1w"] == "TIMEFRAME_W1"
    assert _TIMEFRAME_MAP["1m"] == "TIMEFRAME_M1"
    assert _TIMEFRAME_MAP["1M"] == "TIMEFRAME_MN1"


def test_project_1H_does_not_fall_back_to_daily() -> None:
    assert _TIMEFRAME_MAP.get("1H".strip(), "TIMEFRAME_D1") == "TIMEFRAME_H1"
    assert _TIMEFRAME_MAP.get("4H".strip(), "TIMEFRAME_D1") == "TIMEFRAME_H4"
