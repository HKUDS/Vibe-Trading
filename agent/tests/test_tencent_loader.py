"""Tests for Tencent's daily-only market-data contract."""

from __future__ import annotations

import pandas as pd

from backtest.loaders import tencent_loader


def test_intraday_request_does_not_return_daily_bars(monkeypatch) -> None:
    calls: list[str] = []
    daily = pd.DataFrame(
        {
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [100.0],
        },
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-05")]),
    )
    loader = tencent_loader.DataLoader()
    monkeypatch.setattr(
        tencent_loader,
        "cached_loader_fetch",
        lambda **kwargs: kwargs["fetch"](),
    )
    monkeypatch.setattr(
        loader,
        "_fetch_one",
        lambda code, start, end: calls.append(code) or daily,
    )

    result = loader.fetch(
        ["600519.SH"],
        "2026-01-01",
        "2026-01-31",
        interval="1m",
    )

    assert result == {}
    assert calls == []
