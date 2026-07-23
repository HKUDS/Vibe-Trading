"""Tests for OKX period → bar mapping."""

from __future__ import annotations

from src.trading.connectors.okx.sdk import _BAR_MAP


def test_project_hour_tokens_map_to_hour_not_daily() -> None:
    assert _BAR_MAP.get("1H") == "1H"
    assert _BAR_MAP.get("4H") == "4H"
    assert _BAR_MAP.get("1h") == "1H"
    assert _BAR_MAP.get("4h") == "4H"


def test_minute_month_case_still_distinct() -> None:
    assert _BAR_MAP["1m"] == "1m"
    assert _BAR_MAP["1M"] == "1M"
