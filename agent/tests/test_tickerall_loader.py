"""Tests for tickerall_loader: auth gating, symbol resolution, parsing, batch resilience.

All HTTP is mocked at :func:`backtest.loaders._http.throttled_get_json` (imported
into the loader module), so no test touches a live TickerAll endpoint.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from backtest.loaders import tickerall_loader as tl
from backtest.loaders.tickerall_loader import (
    DataLoader,
    _parse_candles,
    _to_query_base,
    _window_to_hours,
)

# 2024-01-03 and 2024-01-04 at 00:00:00 UTC, epoch seconds.
_TS_JAN3 = 1704240000
_TS_JAN4 = 1704326400
_TS_DEC1 = 1701388800  # 2023-12-01, before a Jan window (trim target)

# Descending order on purpose: the parser must sort ascending.
_EURUSD_BARS = [
    {"timestamp": _TS_JAN4, "open": 1.09, "high": 1.10, "low": 1.08, "close": 1.095, "tickVolume": 200},
    {"timestamp": _TS_JAN3, "open": 1.10, "high": 1.11, "low": 1.09, "close": 1.10, "tickVolume": 100},
]


def _candles(bars):
    """A TickerAll /candles body (top-level array)."""
    return list(bars)


@pytest.fixture(autouse=True)
def _clear_symbol_cache():
    """The loader memoizes the account symbol map per process; isolate each test."""
    tl._symbol_cache.clear()
    yield
    tl._symbol_cache.clear()


def _route(symbols=None, candles=None):
    """Build a throttled_get_json side_effect routing by endpoint."""
    def _side(url, **kwargs):
        if url.endswith("/symbols"):
            return symbols if symbols is not None else []
        if url.endswith("/candles"):
            return candles if candles is not None else []
        raise AssertionError(f"unexpected URL {url}")
    return _side


class TestRegistration:
    """Loader self-registers with the expected metadata."""

    def test_registered_in_registry(self):
        from backtest.loaders import registry

        registry._ensure_registered()
        assert registry.LOADER_REGISTRY.get("tickerall") is DataLoader

    def test_in_valid_sources_and_forex_chain(self):
        from backtest.loaders import registry

        assert "tickerall" in registry.VALID_SOURCES
        assert "tickerall" in registry.FALLBACK_CHAINS["forex"]

    def test_metadata(self):
        assert DataLoader.name == "tickerall"
        assert DataLoader.markets == {"forex"}
        assert DataLoader.requires_auth is True


class TestIsAvailable:
    """Availability is gated on BOTH the key and the account id being set."""

    def test_available_with_key_and_account(self, monkeypatch):
        monkeypatch.setenv("TICKERALL_API_KEY", "secret")
        monkeypatch.setenv("TICKERALL_ACCOUNT_ID", "acct1")
        assert DataLoader().is_available() is True

    def test_unavailable_without_key(self, monkeypatch):
        monkeypatch.delenv("TICKERALL_API_KEY", raising=False)
        monkeypatch.setenv("TICKERALL_ACCOUNT_ID", "acct1")
        assert DataLoader().is_available() is False

    def test_unavailable_without_account(self, monkeypatch):
        monkeypatch.setenv("TICKERALL_API_KEY", "secret")
        monkeypatch.delenv("TICKERALL_ACCOUNT_ID", raising=False)
        assert DataLoader().is_available() is False

    def test_unavailable_with_blank_key(self, monkeypatch):
        monkeypatch.setenv("TICKERALL_API_KEY", "   ")
        monkeypatch.setenv("TICKERALL_ACCOUNT_ID", "acct1")
        assert DataLoader().is_available() is False


class TestSymbolMapping:
    """Base-symbol normalization strips separators and the .FX suffix."""

    def test_slash_pair(self):
        assert _to_query_base("EUR/USD") == "EURUSD"

    def test_fx_suffix(self):
        assert _to_query_base("EURUSD.FX") == "EURUSD"

    def test_uppercased_and_stripped(self):
        assert _to_query_base("xau_usd") == "XAUUSD"


class TestParseCandles:
    """Pure parsing of the JSON body needs no network."""

    def test_sorts_ascending_typed_and_named(self):
        df = _parse_candles(_candles(_EURUSD_BARS), "2024-01-01", "2024-01-31")
        assert list(df.index) == [pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04")]
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.index.name == "trade_date"
        assert df["close"].iloc[0] == 1.10
        for col in df.columns:
            assert df[col].dtype == float

    def test_tick_volume_fallback_and_float(self):
        df = _parse_candles(_candles(_EURUSD_BARS), "2024-01-01", "2024-01-31")
        assert df["volume"].dtype == float
        assert df["volume"].iloc[0] == 100.0  # from tickVolume

    def test_explicit_volume_preferred_over_tickvolume(self):
        bars = [{"timestamp": _TS_JAN3, "open": 1, "high": 2, "low": 0.5, "close": 1.5,
                 "volume": 7, "tickVolume": 999}]
        df = _parse_candles(_candles(bars), "2024-01-01", "2024-01-31")
        assert df["volume"].iloc[0] == 7.0

    def test_window_trims_out_of_range_bars(self):
        bars = [{"timestamp": _TS_DEC1, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "tickVolume": 1}] + _EURUSD_BARS
        df = _parse_candles(_candles(bars), "2024-01-01", "2024-01-31")
        assert list(df.index) == [pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04")]

    def test_wrapped_body_supported(self):
        df = _parse_candles({"candles": _EURUSD_BARS}, "2024-01-01", "2024-01-31")
        assert len(df) == 2

    def test_empty_returns_none(self):
        assert _parse_candles([], "2024-01-01", "2024-01-31") is None
        assert _parse_candles({"candles": []}, "2024-01-01", "2024-01-31") is None
        assert _parse_candles(None, "2024-01-01", "2024-01-31") is None

    def test_incomplete_ohlc_row_dropped(self):
        bars = [{"timestamp": _TS_JAN3, "open": None, "high": 2.0, "low": 0.5, "close": 1.5, "tickVolume": 1}]
        assert _parse_candles(_candles(bars), "2024-01-01", "2024-01-31") is None


class TestWindowToHours:
    """The [start, end] window maps to a positive, capped relative lookback."""

    def test_past_start_positive_and_capped(self):
        assert 1 <= _window_to_hours("2024-01-01", "2024-06-01", "D1") <= tl._MAX_HOURS

    def test_future_start_falls_back_to_minimum(self):
        assert _window_to_hours("2999-01-01", "2999-02-01", "D1") >= 1

    def test_unparseable_start_uses_ceiling(self):
        assert _window_to_hours("not-a-date", "2024-01-01", "D1") == tl._MAX_HOURS


class TestFetch:
    """End-to-end fetch with the HTTP layer mocked (symbols + candles)."""

    def test_fetch_resolves_broker_symbol(self, monkeypatch):
        monkeypatch.setenv("TICKERALL_API_KEY", "secret")
        monkeypatch.setenv("TICKERALL_ACCOUNT_ID", "acct1")
        symbols = [{"symbol": "EURUSDm"}, {"symbol": "XAUUSDm"}]
        with patch.object(tl, "throttled_get_json", side_effect=_route(symbols, _EURUSD_BARS)) as mock_get:
            out = DataLoader().fetch(["EUR/USD"], "2024-01-01", "2024-01-31")
        assert set(out) == {"EUR/USD"}  # keyed by ORIGINAL code
        assert len(out["EUR/USD"]) == 2
        # The broker suffix (Exness "m") was resolved into the candles request.
        candles_call = [c for c in mock_get.call_args_list if c.args[0].endswith("/candles")][0]
        params = candles_call.kwargs["params"]
        assert params["symbol"] == "EURUSDm"
        assert params["timeframe"] == "D1"
        # Bearer auth header carried through.
        assert candles_call.kwargs["headers"]["Authorization"] == "Bearer secret"

    def test_symbol_falls_back_when_list_unavailable(self, monkeypatch):
        monkeypatch.setenv("TICKERALL_API_KEY", "secret")
        monkeypatch.setenv("TICKERALL_ACCOUNT_ID", "acct1")

        def _side(url, **kwargs):
            if url.endswith("/symbols"):
                raise RuntimeError("symbols down")
            return _EURUSD_BARS

        with patch.object(tl, "throttled_get_json", side_effect=_side) as mock_get:
            out = DataLoader().fetch(["EURUSD"], "2024-01-01", "2024-01-31")
        assert set(out) == {"EURUSD"}
        candles_call = [c for c in mock_get.call_args_list if c.args[0].endswith("/candles")][0]
        assert candles_call.kwargs["params"]["symbol"] == "EURUSD"  # base fallback

    def test_one_failing_symbol_does_not_abort_batch(self, monkeypatch):
        monkeypatch.setenv("TICKERALL_API_KEY", "secret")
        monkeypatch.setenv("TICKERALL_ACCOUNT_ID", "acct1")

        def _side(url, **kwargs):
            if url.endswith("/symbols"):
                return []
            if kwargs["params"]["symbol"] == "BAD":
                raise RuntimeError("boom")
            return _EURUSD_BARS

        with patch.object(tl, "throttled_get_json", side_effect=_side):
            out = DataLoader().fetch(["BAD", "EURUSD"], "2024-01-01", "2024-01-31")
        assert set(out) == {"EURUSD"}

    def test_empty_result_symbol_omitted(self, monkeypatch):
        monkeypatch.setenv("TICKERALL_API_KEY", "secret")
        monkeypatch.setenv("TICKERALL_ACCOUNT_ID", "acct1")
        with patch.object(tl, "throttled_get_json", side_effect=_route([], [])):
            out = DataLoader().fetch(["EURUSD"], "2024-01-01", "2024-01-31")
        assert out == {}

    def test_unknown_interval_returns_empty(self, monkeypatch):
        monkeypatch.setenv("TICKERALL_API_KEY", "secret")
        monkeypatch.setenv("TICKERALL_ACCOUNT_ID", "acct1")
        with patch.object(tl, "throttled_get_json") as mock_get:
            out = DataLoader().fetch(["EURUSD"], "2024-01-01", "2024-01-31", interval="3y")
        assert out == {}
        mock_get.assert_not_called()

    def test_not_available_returns_empty(self, monkeypatch):
        monkeypatch.delenv("TICKERALL_API_KEY", raising=False)
        monkeypatch.delenv("TICKERALL_ACCOUNT_ID", raising=False)
        with patch.object(tl, "throttled_get_json") as mock_get:
            out = DataLoader().fetch(["EURUSD"], "2024-01-01", "2024-01-31")
        assert out == {}
        mock_get.assert_not_called()
