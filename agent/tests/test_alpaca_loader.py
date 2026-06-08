"""Tests for the Alpaca US-equity data loader.

The Alpaca SDK is never imported here: ``_normalize_bars`` is a pure function,
and ``fetch`` is exercised with ``_fetch_bars`` monkeypatched to return scripted
bars. This keeps the suite hermetic (no network, no ``alpaca-py`` dependency).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

import backtest.loaders.alpaca_loader as al
from backtest.loaders.alpaca_loader import DataLoader, _normalize_bars, _to_alpaca_symbol


@dataclass
class _Bar:
    """Minimal stand-in for an Alpaca ``Bar`` object."""

    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float


def _bar(ts: str, base: float = 100.0) -> _Bar:
    return _Bar(pd.Timestamp(ts, tz="UTC"), base, base + 1, base - 1, base + 0.5, 1000.0)


# --------------------------------------------------------------------------- #
# Symbol mapping
# --------------------------------------------------------------------------- #


def test_symbol_strips_us_suffix():
    assert _to_alpaca_symbol("AAPL.US") == "AAPL"
    assert _to_alpaca_symbol(" tsla.us ") == "TSLA"
    assert _to_alpaca_symbol("MSFT") == "MSFT"


# --------------------------------------------------------------------------- #
# Normalization: schema + timezone handling
# --------------------------------------------------------------------------- #


def test_normalize_schema_and_sort():
    # Deliberately out of order; UTC timestamps during an intraday session.
    bars = [_bar("2026-05-01 14:00:00", 101), _bar("2026-05-01 13:30:00", 100)]
    df = _normalize_bars(bars, "5m")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "trade_date"
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.is_monotonic_increasing


def test_normalize_intraday_converts_utc_to_et():
    # 13:30 UTC == 09:30 America/New_York (EDT, market open), tz-naive after.
    df = _normalize_bars([_bar("2026-05-01 13:30:00")], "5m")
    assert df.index.tz is None
    assert df.index[0] == pd.Timestamp("2026-05-01 09:30:00")


def test_normalize_daily_collapses_to_date():
    # A bar stamped 13:30 UTC on the trading day collapses to that ET date.
    df = _normalize_bars([_bar("2026-05-01 13:30:00")], "1D")
    assert df.index.tz is None
    assert df.index[0] == pd.Timestamp("2026-05-01 00:00:00")


def test_normalize_empty_returns_empty_schema():
    df = _normalize_bars([], "5m")
    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


# --------------------------------------------------------------------------- #
# fetch(): symbol re-keying via a mocked batch fetch
# --------------------------------------------------------------------------- #


def test_fetch_rekeys_to_original_codes(monkeypatch):
    loader = DataLoader()
    monkeypatch.setattr(
        loader,
        "_fetch_bars",
        lambda symbols, s, e, i: {"AAPL": [_bar("2026-05-01 13:30:00"), _bar("2026-05-01 13:35:00")]},
    )
    out = loader.fetch(["AAPL.US"], "2026-05-01", "2026-05-02", interval="5m")
    assert set(out) == {"AAPL.US"}  # result keyed by the original project symbol
    df = out["AAPL.US"]
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "trade_date"


def test_fetch_empty_codes_short_circuits():
    assert DataLoader().fetch([], "2026-05-01", "2026-05-02") == {}


# --------------------------------------------------------------------------- #
# is_available(): gated on SDK presence + credentials
# --------------------------------------------------------------------------- #


def test_is_available_false_without_creds(monkeypatch):
    from src.trading.connectors.alpaca.sdk import AlpacaConfig

    loader = DataLoader()
    loader._cfg = AlpacaConfig(api_key="", secret_key="")
    monkeypatch.setattr("src.trading.connectors.alpaca.sdk.alpaca_available", lambda: True)
    assert loader.is_available() is False


def test_is_available_true_with_creds(monkeypatch):
    from src.trading.connectors.alpaca.sdk import AlpacaConfig

    loader = DataLoader()
    loader._cfg = AlpacaConfig(api_key="key", secret_key="secret")
    monkeypatch.setattr("src.trading.connectors.alpaca.sdk.alpaca_available", lambda: True)
    assert loader.is_available() is True


def test_is_available_false_when_sdk_missing(monkeypatch):
    from src.trading.connectors.alpaca.sdk import AlpacaConfig

    loader = DataLoader()
    loader._cfg = AlpacaConfig(api_key="key", secret_key="secret")
    monkeypatch.setattr("src.trading.connectors.alpaca.sdk.alpaca_available", lambda: False)
    assert loader.is_available() is False


# --------------------------------------------------------------------------- #
# Registry wiring
# --------------------------------------------------------------------------- #


def test_registered_and_preferred_for_us_equity():
    from backtest.loaders.registry import (
        FALLBACK_CHAINS,
        LOADER_REGISTRY,
        _ensure_registered,
    )

    _ensure_registered()
    assert "alpaca" in LOADER_REGISTRY
    assert FALLBACK_CHAINS["us_equity"][0] == "alpaca"
    assert "yfinance" in FALLBACK_CHAINS["us_equity"]  # still the fallback
