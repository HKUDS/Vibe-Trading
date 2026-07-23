"""CCXT interval map must keep weekly/monthly tokens (not silent daily)."""

from __future__ import annotations

from backtest.loaders.ccxt_loader import _INTERVAL_MAP


def test_ccxt_interval_map_keeps_week_and_month() -> None:
    assert _INTERVAL_MAP["1W"] == "1w"
    assert _INTERVAL_MAP["1M"] == "1M"
    assert _INTERVAL_MAP["1D"] == "1d"
    assert _INTERVAL_MAP["1m"] == "1m"
