"""India broker data-bridge loader: envelope adaptation + availability gating.

The loader adapts Shoonya/Dhan ``get_historical_bars`` into the OHLCV frame.
Tests inject a fake broker SDK via ``_resolve_broker`` so no real SDK/creds are
needed; the loader stays unavailable (and inert) when no broker is configured.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from backtest.loaders import india_broker_loader as mod
from backtest.loaders.india_broker_loader import DataLoader, _base_symbol, _exchange_for


def _epoch(date_str: str) -> int:
    d = pd.Timestamp(date_str).date()
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())


class _FakeSDK:
    """Minimal stand-in exposing ``get_historical_bars`` like the real connectors."""

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


def test_unavailable_when_no_broker(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_resolve_broker", lambda: (None, None))
    loader = DataLoader()
    assert loader.is_available() is False
    assert loader.fetch(["RELIANCE.NS"], "2024-04-01", "2024-04-30") == {}


def test_fetch_parses_and_clips_window(monkeypatch) -> None:
    fake = _FakeSDK()
    monkeypatch.setattr(mod, "_resolve_broker", lambda: ("shoonya", fake))
    loader = DataLoader()
    assert loader.is_available() is True

    out = loader.fetch(["RELIANCE.NS"], "2024-04-01", "2024-04-30")
    assert "RELIANCE.NS" in out
    df = out["RELIANCE.NS"]
    # The 2024-05-10 bar is outside the window and must be clipped away.
    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "trade_date"
    # Broker received the bare symbol on the right exchange.
    assert fake.calls[0]["symbol"] == "RELIANCE"
    assert fake.calls[0]["exchange"] == "NSE"


def test_error_envelope_yields_no_data(monkeypatch) -> None:
    class _ErrSDK:
        def get_historical_bars(self, symbol, **kw):
            return {"status": "error", "error": "no session"}

    monkeypatch.setattr(mod, "_resolve_broker", lambda: ("dhan", _ErrSDK()))
    loader = DataLoader()
    assert loader.fetch(["TCS.NS"], "2024-04-01", "2024-04-30") == {}
