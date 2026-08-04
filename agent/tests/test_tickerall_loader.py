"""Tests for tickerall_loader: the four review-contract guarantees plus parsing.

All HTTP is mocked at :func:`backtest.loaders._http.throttled_get_json` (imported
into the loader module), so no test touches a live TickerAll endpoint. The four
contract points these tests pin down:

  1. Explicit-only  - registered as a valid source, never in a fallback chain.
  2. Read-only      - every request is a GET to a read endpoint; no write path.
  3. Cache identity - both the symbol memo and the frame cache key include the
                      account id AND the base URL, so two accounts never collide.
  4. Partial = error - a truncated/partial window raises IncompleteHistoryError
                       rather than returning a silently short series.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from backtest.loaders import tickerall_loader as tl
from backtest.loaders.tickerall_loader import (
    DataLoader,
    IncompleteHistoryError,
    _parse_candles,
    _to_query_base,
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


def _resp(bars, *, truncated=False, coverage="full", stop_reason=None):
    """A range-mode /candles body: {candles, truncated, coverage, stopReason, ...}."""
    return {
        "candles": list(bars),
        "served": len(bars),
        "count": len(bars),
        "coverage": coverage,
        "truncated": truncated,
        "stopReason": stop_reason,
    }


def _route(symbols=None, candles=None):
    """Build a throttled_get_json side_effect routing by endpoint."""
    def _side(url, **kwargs):
        if url.endswith("/symbols"):
            return symbols if symbols is not None else []
        if url.endswith("/candles"):
            return candles if candles is not None else _resp([])
        raise AssertionError(f"unexpected URL {url}")
    return _side


def _set_creds(monkeypatch, key="secret", account="acct1", base="https://api.tickerall.com"):
    """Patch the loader's config accessors directly (no config-cache dependency)."""
    monkeypatch.setattr(tl, "_api_key", lambda: key)
    monkeypatch.setattr(tl, "_account_id", lambda: account)
    monkeypatch.setattr(tl, "_base_url", lambda: base)


def requests_like_http_error(resp):
    """An exception shaped like ``requests.HTTPError``: it carries a ``.response`` with
    ``.status_code`` + ``.json()`` — what ``throttled_get_json``'s ``raise_for_status``
    raises, and what ``_reraise_if_range_too_large`` duck-types on."""
    err = Exception("HTTP error")
    err.response = resp
    return err


@pytest.fixture(autouse=True)
def _clear_symbol_cache():
    """The loader memoizes the account symbol map per process; isolate each test."""
    tl._symbol_cache.clear()
    yield
    tl._symbol_cache.clear()


# ---------------------------------------------------------------------------
# (1) Explicit-only + registration
# ---------------------------------------------------------------------------
class TestRegistrationAndExplicitOnly:
    def test_registered_in_registry(self):
        from backtest.loaders import registry

        registry._ensure_registered()
        assert registry.LOADER_REGISTRY.get("tickerall") is DataLoader

    def test_in_valid_sources(self):
        from backtest.loaders import registry

        assert "tickerall" in registry.VALID_SOURCES

    def test_never_in_any_fallback_chain(self):
        """Contract 1: explicit-only. A user's broker credential is used only on a
        deliberate source="tickerall" request, never silently as a fallback."""
        from backtest.loaders import registry

        for market, chain in registry.FALLBACK_CHAINS.items():
            assert "tickerall" not in chain, f"tickerall must not be in the {market} chain"

    def test_metadata(self):
        assert DataLoader.name == "tickerall"
        assert DataLoader.markets == {"forex"}
        assert DataLoader.requires_auth is True


class TestIsAvailable:
    """Availability is gated on BOTH the key and the account id being set."""

    def test_available_with_key_and_account(self, monkeypatch):
        _set_creds(monkeypatch)
        assert DataLoader().is_available() is True

    def test_unavailable_without_key(self, monkeypatch):
        _set_creds(monkeypatch, key="")
        assert DataLoader().is_available() is False

    def test_unavailable_without_account(self, monkeypatch):
        _set_creds(monkeypatch, account="")
        assert DataLoader().is_available() is False


class TestSymbolMapping:
    """Base-symbol normalization strips separators and the .FX suffix."""

    def test_slash_pair(self):
        assert _to_query_base("EUR/USD") == "EURUSD"

    def test_fx_suffix(self):
        assert _to_query_base("EURUSD.FX") == "EURUSD"

    def test_uppercased_and_stripped(self):
        assert _to_query_base("xau_usd") == "XAUUSD"


class TestSymbolResolution:
    """Broker-suffix resolution against the account's own symbol list."""

    def test_exact_match_shortest_wins(self, monkeypatch):
        _set_creds(monkeypatch)
        with patch.object(tl, "throttled_get_json", side_effect=_route(symbols=["EURUSDz", "EURUSDm"])):
            assert tl._resolve_symbol("EURUSD", "acct1", "secret") == "EURUSDm"

    def test_prefix_match_when_no_exact(self, monkeypatch):
        _set_creds(monkeypatch)
        with patch.object(tl, "throttled_get_json", side_effect=_route(symbols=["EURUSDmicro"])):
            assert tl._resolve_symbol("EURUSD", "acct1", "secret") == "EURUSDmicro"

    def test_falls_back_to_base_when_list_empty(self, monkeypatch):
        _set_creds(monkeypatch)
        with patch.object(tl, "throttled_get_json", side_effect=_route(symbols=[])):
            assert tl._resolve_symbol("EURUSD", "acct1", "secret") == "EURUSD"


# ---------------------------------------------------------------------------
# (2) Read-only
# ---------------------------------------------------------------------------
class TestReadOnly:
    def test_only_get_read_endpoints_are_touched(self, monkeypatch):
        """Contract 2: every request is a GET to a read endpoint; the module has
        no trade/order/mutation path."""
        _set_creds(monkeypatch)
        seen = []

        def _side(url, **kwargs):
            seen.append(url)
            if url.endswith("/symbols"):
                return ["EURUSDm"]
            return _resp(_EURUSD_BARS)

        with patch.object(tl, "throttled_get_json", side_effect=_side):
            DataLoader().fetch(["EURUSD"], "2024-01-03", "2024-01-04", interval="1D")

        assert seen, "expected at least one request"
        assert all(u.endswith("/symbols") or u.endswith("/candles") for u in seen)
        # The loader imports only the GET helper - there is no write surface.
        assert not hasattr(tl, "throttled_post_json")


# ---------------------------------------------------------------------------
# (3) Cache identity includes account id + base URL
# ---------------------------------------------------------------------------
class TestCacheIdentity:
    def test_frame_cache_key_includes_account_and_base_host(self, monkeypatch):
        """Contract 3: the frame cache key carries the account + base host, so two
        accounts (or two endpoints) never share a cached series."""
        _set_creds(monkeypatch, account="ACCT9", base="https://staging.example.com")
        captured = {}

        def _fake_cached(*, source, symbol, timeframe, start_date, end_date, fields, fetch):
            captured["source"] = source
            captured["symbol"] = symbol
            return fetch()

        monkeypatch.setattr(tl, "cached_loader_fetch", _fake_cached)
        with patch.object(tl, "throttled_get_json", side_effect=_route(candles=_resp(_EURUSD_BARS))):
            DataLoader().fetch(["EURUSD"], "2024-01-01", "2024-01-31", interval="1D")

        assert "ACCT9" in captured["symbol"]
        assert "staging.example.com" in captured["symbol"]

    def test_symbol_memo_not_shared_across_base_urls(self, monkeypatch):
        """The symbol memo is keyed by (base_url, account): the SAME account id on
        two endpoints resolves independently (no cross-endpoint bleed)."""
        calls = []

        def _side(url, **kwargs):
            calls.append(url)
            return ["EURUSDm"]

        monkeypatch.setattr(tl, "_api_key", lambda: "k")
        monkeypatch.setattr(tl, "_account_id", lambda: "ACCT")
        monkeypatch.setattr(tl, "_base_url", lambda: "https://a.example.com")
        with patch.object(tl, "throttled_get_json", side_effect=_side):
            tl._account_symbols("ACCT", "k")
        monkeypatch.setattr(tl, "_base_url", lambda: "https://b.example.com")
        with patch.object(tl, "throttled_get_json", side_effect=_side):
            tl._account_symbols("ACCT", "k")

        assert len([u for u in calls if u.endswith("/symbols")]) == 2


# ---------------------------------------------------------------------------
# (4) Partial history is an error, not a short series  +  range mode
# ---------------------------------------------------------------------------
class TestRangeModeAndCompleteness:
    def test_fetch_uses_from_to_range_not_hours(self, monkeypatch):
        _set_creds(monkeypatch)
        seen = {}

        def _side(url, **kwargs):
            if url.endswith("/symbols"):
                return []
            seen.update(kwargs.get("params", {}))
            return _resp(_EURUSD_BARS)

        with patch.object(tl, "throttled_get_json", side_effect=_side):
            DataLoader().fetch(["EURUSD"], "2024-01-03", "2024-01-04", interval="1D")

        assert seen.get("from") == "2024-01-03T00:00:00Z"
        assert seen.get("to") == "2024-01-04T23:59:59Z"
        assert "hours" not in seen  # exact range, not the old relative-lookback hack

    def test_truncated_raises_incomplete(self, monkeypatch):
        """Contract 4: a truncated walk is an error, not a short series."""
        _set_creds(monkeypatch)
        resp = _resp(_EURUSD_BARS, truncated=True, stop_reason="deadline")
        with patch.object(tl, "throttled_get_json", side_effect=_route(candles=resp)):
            with pytest.raises(IncompleteHistoryError):
                DataLoader().fetch(["EURUSD"], "2019-01-01", "2024-01-31", interval="1D")

    def test_partial_coverage_raises_incomplete(self, monkeypatch):
        _set_creds(monkeypatch)
        resp = _resp(_EURUSD_BARS, coverage="partial", stop_reason="unsupported")
        with patch.object(tl, "throttled_get_json", side_effect=_route(candles=resp)):
            with pytest.raises(IncompleteHistoryError):
                DataLoader().fetch(["EURUSD"], "2024-01-01", "2024-01-31", interval="1D")

    def test_incomplete_propagates_and_is_not_swallowed(self, monkeypatch):
        """The batch loop swallows transient per-symbol errors, but a partial
        window must propagate so a backtest fails loudly."""
        _set_creds(monkeypatch)
        resp = _resp(_EURUSD_BARS, truncated=True)
        with patch.object(tl, "throttled_get_json", side_effect=_route(candles=resp)):
            with pytest.raises(IncompleteHistoryError):
                DataLoader().fetch(["EURUSD", "XAUUSD"], "2019-01-01", "2024-01-31", interval="1D")

    def test_range_too_large_400_raises_incomplete(self, monkeypatch):
        """Contract 4, the REAL truncation path (caught live): a window wider than one
        request is rejected with a 400 `range_too_large`, NOT a 200 `truncated`. It must
        raise IncompleteHistoryError, not be swallowed as a skipped symbol."""
        _set_creds(monkeypatch)

        class _Resp:
            status_code = 400

            def json(self):
                return {"error": "range_too_large", "maxWindowDays": 1830, "maxBars": 100000}

        err = requests_like_http_error(_Resp())

        def _side(url, **kwargs):
            if url.endswith("/symbols"):
                return []
            raise err

        with patch.object(tl, "throttled_get_json", side_effect=_side):
            with pytest.raises(IncompleteHistoryError):
                DataLoader().fetch(["EURUSD"], "2005-01-01", "2024-12-31", interval="1D")

    def test_other_400_stays_a_transient_skip(self, monkeypatch):
        """A non-range 4xx (e.g. an unknown symbol) is NOT incomplete-history — it stays a
        transient per-symbol skip so one bad symbol never poisons the batch."""
        _set_creds(monkeypatch)

        class _Resp:
            status_code = 400

            def json(self):
                return {"error": "symbol_not_found"}

        err = requests_like_http_error(_Resp())

        def _side(url, **kwargs):
            if url.endswith("/symbols"):
                return []
            raise err

        with patch.object(tl, "throttled_get_json", side_effect=_side):
            out = DataLoader().fetch(["EURUSD"], "2024-01-01", "2024-01-31", interval="1D")
        assert out == {}

    def test_complete_window_returns_frame(self, monkeypatch):
        _set_creds(monkeypatch)
        with patch.object(tl, "throttled_get_json", side_effect=_route(candles=_resp(_EURUSD_BARS))):
            out = DataLoader().fetch(["EURUSD"], "2024-01-01", "2024-01-31", interval="1D")
        assert "EURUSD" in out
        assert list(out["EURUSD"].index) == [pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04")]

    def test_transient_symbol_error_is_swallowed(self, monkeypatch):
        """A network blip on one symbol logs+skips (never poisons the batch)."""
        _set_creds(monkeypatch)

        def _side(url, **kwargs):
            if url.endswith("/symbols"):
                return []
            raise RuntimeError("network blip")

        with patch.object(tl, "throttled_get_json", side_effect=_side):
            out = DataLoader().fetch(["EURUSD"], "2024-01-01", "2024-01-31", interval="1D")
        assert out == {}

    def test_unknown_interval_rejected(self, monkeypatch):
        _set_creds(monkeypatch)
        with patch.object(tl, "throttled_get_json", side_effect=_route(candles=_resp(_EURUSD_BARS))):
            assert DataLoader().fetch(["EURUSD"], "2024-01-01", "2024-01-31", interval="3s") == {}


# ---------------------------------------------------------------------------
# Pure parsing (no network)
# ---------------------------------------------------------------------------
class TestParseCandles:
    def test_sorts_ascending_typed_and_named(self):
        df = _parse_candles(_resp(_EURUSD_BARS), "2024-01-01", "2024-01-31")
        assert list(df.index) == [pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04")]
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.index.name == "trade_date"
        assert df["close"].iloc[0] == 1.10
        for col in df.columns:
            assert df[col].dtype == float

    def test_tick_volume_fallback_and_float(self):
        df = _parse_candles(_resp(_EURUSD_BARS), "2024-01-01", "2024-01-31")
        assert df["volume"].dtype == float
        assert df["volume"].iloc[0] == 100.0  # from tickVolume

    def test_explicit_volume_preferred_over_tickvolume(self):
        bars = [{"timestamp": _TS_JAN3, "open": 1, "high": 2, "low": 0.5, "close": 1.5,
                 "volume": 7, "tickVolume": 999}]
        df = _parse_candles(_resp(bars), "2024-01-01", "2024-01-31")
        assert df["volume"].iloc[0] == 7.0

    def test_window_trims_out_of_range_bars(self):
        bars = [{"timestamp": _TS_DEC1, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "tickVolume": 1}] + _EURUSD_BARS
        df = _parse_candles(_resp(bars), "2024-01-01", "2024-01-31")
        assert list(df.index) == [pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04")]

    def test_empty_body_returns_none(self):
        assert _parse_candles(_resp([]), "2024-01-01", "2024-01-31") is None

    def test_top_level_array_body_still_parses(self):
        # Back-compat: a bare list body (no wrapper) still parses.
        df = _parse_candles(list(_EURUSD_BARS), "2024-01-01", "2024-01-31")
        assert len(df) == 2
