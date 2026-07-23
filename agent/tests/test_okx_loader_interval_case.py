"""OKX loader must keep lowercase 1h/4h as hour bars, not silent daily."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backtest.loaders import okx as okx_mod


def _fetch_with_interval(interval: str) -> list[str]:
    seen: list[str] = []

    def fake_fetch(self, session, symbol, start_ts, end_ts, bar, max_pages, prefer_history=False):
        seen.append(bar)
        return None

    with patch.object(okx_mod.DataLoader, "_fetch_candles", fake_fetch):
        with patch.object(okx_mod.DataLoader, "_should_use_history", return_value=False):
            with patch.object(okx_mod, "_okx_session", return_value=MagicMock()):
                okx_mod.DataLoader().fetch(
                    ["BTC-USDT"], "2024-01-01", "2024-01-02", interval=interval
                )
    return seen


def test_lowercase_one_hour_fetches_hour_bars_not_daily() -> None:
    assert _fetch_with_interval("1h") == ["1H"]


def test_lowercase_four_hour_fetches_four_hour_bars() -> None:
    assert _fetch_with_interval("4h") == ["4H"]


def test_project_style_one_hour_still_works() -> None:
    assert _fetch_with_interval("1H") == ["1H"]


def test_unsupported_interval_rejects_without_daily_fallback() -> None:
    seen = _fetch_with_interval("2H")
    assert seen == []
