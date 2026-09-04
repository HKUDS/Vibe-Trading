"""Zerodha Kite Connect broker-bridge loader tests.

Mirrors test_india_broker_loader.py: injects a fake Zerodha SDK via
``_resolve_broker`` so no real SDK/creds are needed, and verifies the loader
(1) discovers zerodha, (2) maps symbols/exchanges, (3) parses + clips the
envelope the same way it does for shoonya/dhan.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from backtest.loaders import india_broker_loader as mod
from backtest.loaders.india_broker_loader import DataLoader, _base_symbol, _exchange_for


def _epoch(date_str: str) -> int:
    d = pd.Timestamp(date_str).date()
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())


class _FakeZerodhaSDK:
    """Minimal stand-in exposing ``get_historical_bars`` like the real SDK."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_historical_bars(self, symbol, *, exchange="NSE", period="1d", limit=90):
        self.calls.append({"symbol": symbol, "exchange": exchange, "period": period})
        return {
            "status": "ok",
            "symbol": symbol,
            "bars": [
                {"time": _epoch("2024-04-01"), "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
                {"time": _epoch("2024-04-02"), "open": 100.5, "high": 102, "low": 100, "close": 101.5, "volume": 1200},
                {"time": _epoch("2024-05-10"), "open": 110, "high": 112, "low": 109, "close": 111, "volume": 1500},
            ],
        }


def test_symbol_and_exchange_mapping() -> None:
    assert _base_symbol("RELIANCE.NS") == "RELIANCE"
    assert _base_symbol("500325.BO") == "500325"
    assert _exchange_for("RELIANCE.NS") == "NSE"
    assert _exchange_for("500325.BO") == "BSE"


def test_zerodha_discovery(monkeypatch) -> None:
    fake = _FakeZerodhaSDK()
    monkeypatch.setattr(mod, "_resolve_broker", lambda: ("zerodha", fake))
    loader = DataLoader()
    assert loader.is_available() is True
    result = loader.fetch(["RELIANCE.NS"], "2024-04-01", "2024-04-30")
    assert "RELIANCE.NS" in result
    df = result["RELIANCE.NS"]
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    # window clipped to April only (the May bar is dropped)
    assert len(df) == 2
    assert fake.calls[0]["symbol"] == "RELIANCE"
    assert fake.calls[0]["exchange"] == "NSE"


def test_zerodha_unavailable_when_no_broker(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_resolve_broker", lambda: (None, None))
    loader = DataLoader()
    assert loader.is_available() is False
    assert loader.fetch(["RELIANCE.NS"], "2024-04-01", "2024-04-30") == {}
