"""AKShare daily map must accept connector-style lowercase 1d/1w aliases."""

from __future__ import annotations

from backtest.loaders.akshare_loader import _INTERVAL_MAP_DAILY


def test_lowercase_1d_and_1w_map_like_project_tokens() -> None:
    assert _INTERVAL_MAP_DAILY["1d"] == _INTERVAL_MAP_DAILY["1D"] == "daily"
    assert _INTERVAL_MAP_DAILY["1w"] == _INTERVAL_MAP_DAILY["1W"] == "weekly"


def test_hour_token_still_absent_from_daily_map() -> None:
    assert "1H" not in _INTERVAL_MAP_DAILY
    assert "1h" not in _INTERVAL_MAP_DAILY
