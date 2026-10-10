"""Tests for AKShare loader symbol routing.

Pins issues #50 (ETF) and #54 (forex): the previous _fetch_one routed every
unrecognized code to stock_zh_a_hist, masking ETFs (518880.SH) and forex pairs
(EURUSD) as broken A-shares. These tests use mocks so they don't hit the
network — real-data smoke is in tests/_smoke_akshare_real.py if/when needed.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from backtest.loaders.akshare_loader import (
    DataLoader,
    _is_a_share,
    _is_etf_listed,
    _is_forex,
    _is_hk,
    _is_us,
)
from tests.loader_contract import assert_loader_contract


# ---------------------------------------------------------------------------
# Predicate tests
# ---------------------------------------------------------------------------


class TestIsETFListed:
    @pytest.mark.parametrize("code", [
        "518880.SH",  # gold ETF (issue #50)
        "510300.SH",  # CSI 300 ETF
        "159915.SZ",  # ChiNext ETF
        "161005.SZ",  # LOF
    ])
    def test_etf_codes_match(self, code: str) -> None:
        assert _is_etf_listed(code)

    @pytest.mark.parametrize("code", [
        "600519.SH",   # Moutai — A-share, not ETF
        "000001.SZ",   # Ping An Bank — A-share
        "300750.SZ",   # CATL — ChiNext stock
        "AAPL.US",     # not Chinese
        "EURUSD",      # forex
        "12345.SH",    # malformed
        "5188800.SH",  # too long
    ])
    def test_non_etf_codes_skip(self, code: str) -> None:
        assert not _is_etf_listed(code)


class TestIsForex:
    def test_eurusd_matches(self) -> None:
        assert _is_forex("EURUSD")

    def test_lowercase_matches(self) -> None:
        assert _is_forex("eurusd")

    def test_fx_suffix_matches(self) -> None:
        assert _is_forex("EURUSD.FX")

    def test_slash_form_matches(self) -> None:
        # Canonical project form — required for the mt5 → akshare fallback.
        assert _is_forex("EUR/USD")

    def test_a_share_does_not_match(self) -> None:
        assert not _is_forex("600519.SH")

    def test_unknown_pair_does_not_match(self) -> None:
        # "ZZZZZZ" isn't in akshare's symbol_market_map
        assert not _is_forex("ZZZZZZ")


# ---------------------------------------------------------------------------
# Routing tests — verify _fetch_one dispatches to the right endpoint without
# actually hitting AKShare.
# ---------------------------------------------------------------------------


def _stub_etf_response() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
        "open": [5.0, 5.1],
        "high": [5.2, 5.3],
        "low": [4.9, 5.0],
        "close": [5.15, 5.25],
        "volume": [1000, 1100],
    })


def _stub_forex_response() -> pd.DataFrame:
    return pd.DataFrame({
        "日期": pd.to_datetime(["2024-01-02", "2024-01-03"]),
        "代码": ["EURUSD", "EURUSD"],
        "名称": ["欧元兑美元", "欧元兑美元"],
        "今开": [1.10, 1.11],
        "最新价": [1.105, 1.115],
        "最高": [1.12, 1.13],
        "最低": [1.09, 1.10],
        "振幅": [0.5, 0.4],
    })


def _stub_a_share_response() -> pd.DataFrame:
    return pd.DataFrame({
        "日期": pd.to_datetime(["2024-01-02"]),
        "开盘": [1700.0],
        "最高": [1720.0],
        "最低": [1690.0],
        "收盘": [1710.0],
        "成交量": [100000],
    })


def _stub_futures_dated_response() -> pd.DataFrame:
    """Shape of ``futures_zh_daily_sina`` as the live endpoint returns it.

    English column names, plus ``hold``/``settle`` which the OHLCV schema
    drops, and — the part that matters — the contract's *whole life*: this
    endpoint takes no date range, so four days are returned here and the
    loader is responsible for cutting them to the requested window.
    """
    return pd.DataFrame({
        "date": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
        "open": [3340.0, 3364.0, 3401.0, 3410.0],
        "high": [3376.0, 3407.0, 3415.0, 3430.0],
        "low": [3322.0, 3362.0, 3396.0, 3405.0],
        "close": [3369.0, 3407.0, 3413.0, 3425.0],
        "volume": [546, 391, 850, 900],
        "hold": [361, 641, 784, 810],
        "settle": [3348.0, 3388.0, 3406.0, 3420.0],
    })


def _stub_futures_main_response() -> pd.DataFrame:
    """Shape of ``futures_main_sina``: Chinese names carrying a ``价`` suffix.

    ``开盘价`` is NOT the ``开盘`` spelling ``_normalize`` learned from the
    equity endpoints, so a loader that forwards this frame unmapped selects an
    empty column set.
    """
    return pd.DataFrame({
        "日期": ["2024-01-02", "2024-01-03"],
        "开盘价": [3135, 3103],
        "最高价": [3135, 3119],
        "最低价": [3097, 3085],
        "收盘价": [3104, 3111],
        "成交量": [697016, 841618],
        "持仓量": [1548351, 1562948],
        "动态结算价": [3113, 3098],
    })


@pytest.fixture
def fake_akshare(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Install a stub `akshare` module with mocked endpoints."""
    fake = SimpleNamespace(
        fund_etf_hist_sina=MagicMock(return_value=_stub_etf_response()),
        forex_hist_em=MagicMock(return_value=_stub_forex_response()),
        stock_zh_a_hist=MagicMock(return_value=_stub_a_share_response()),
        stock_us_hist=MagicMock(return_value=pd.DataFrame()),
        stock_hk_hist=MagicMock(return_value=pd.DataFrame()),
        futures_zh_daily_sina=MagicMock(return_value=_stub_futures_dated_response()),
        futures_main_sina=MagicMock(return_value=_stub_futures_main_response()),
    )
    monkeypatch.setitem(sys.modules, "akshare", fake)
    return fake


class TestRouting:
    def test_etf_routes_to_fund_etf_hist_sina(self, fake_akshare: SimpleNamespace) -> None:
        loader = DataLoader()
        df = loader._fetch_one("518880.SH", "2024-01-01", "2024-12-31", "1D")

        fake_akshare.fund_etf_hist_sina.assert_called_once_with(symbol="sh518880")
        fake_akshare.stock_zh_a_hist.assert_not_called()
        assert df is not None
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) == 2
        assert_loader_contract(df, context="canonical frame")

    def test_etf_sz_uses_sz_prefix(self, fake_akshare: SimpleNamespace) -> None:
        loader = DataLoader()
        loader._fetch_one("159915.SZ", "2024-01-01", "2024-12-31", "1D")

        fake_akshare.fund_etf_hist_sina.assert_called_once_with(symbol="sz159915")

    def test_forex_routes_to_forex_hist_em(self, fake_akshare: SimpleNamespace) -> None:
        loader = DataLoader()
        df = loader._fetch_one("EURUSD", "2024-01-01", "2024-12-31", "1D")

        fake_akshare.forex_hist_em.assert_called_once_with(symbol="EURUSD")
        fake_akshare.stock_zh_a_hist.assert_not_called()
        assert df is not None
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        # forex has no volume — should be zero-filled
        assert (df["volume"] == 0.0).all()
        # 最新价 → close mapping
        assert df.iloc[0]["close"] == pytest.approx(1.105)

    def test_forex_strips_fx_suffix(self, fake_akshare: SimpleNamespace) -> None:
        loader = DataLoader()
        loader._fetch_one("EURUSD.FX", "2024-01-01", "2024-12-31", "1D")
        fake_akshare.forex_hist_em.assert_called_once_with(symbol="EURUSD")

    def test_a_share_still_routes_to_stock_zh_a_hist(
        self, fake_akshare: SimpleNamespace
    ) -> None:
        loader = DataLoader()
        loader._fetch_one("600519.SH", "2024-01-01", "2024-12-31", "1D")

        fake_akshare.stock_zh_a_hist.assert_called_once()
        fake_akshare.fund_etf_hist_sina.assert_not_called()
        fake_akshare.forex_hist_em.assert_not_called()


# ---------------------------------------------------------------------------
# Futures routing (HKUDS/Vibe-Trading#1395)
# ---------------------------------------------------------------------------


class TestFuturesRouting:
    """The third instance of this file's founding bug.

    ETFs (#50) and forex (#54) were each masked as broken A-shares by the
    ``# Default: try A-share`` fallthrough. Futures were the same: the chain
    named akshare as a futures source, ``markets`` advertised it, and every
    contract reached ``stock_zh_a_hist``.
    """

    def test_dated_contract_routes_to_sina_daily(
        self, fake_akshare: SimpleNamespace
    ) -> None:
        loader = DataLoader()
        df = loader._fetch_one("RB2601", "2024-01-01", "2024-12-31", "1D")

        fake_akshare.futures_zh_daily_sina.assert_called_once_with(symbol="RB2601")
        fake_akshare.stock_zh_a_hist.assert_not_called()
        assert df is not None
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        # hold/settle are not OHLCV and must not survive into the frame.
        assert "hold" not in df.columns and "settle" not in df.columns

    def test_exchange_suffix_is_stripped_before_the_call(
        self, fake_akshare: SimpleNamespace
    ) -> None:
        """Sina raises on a suffixed code rather than returning empty.

        ``futures_zh_daily_sina("RB2601.SHFE")`` fails inside akshare with
        ``ValueError: Length mismatch``, so a loader that forwards the suffix
        turns every exchange-qualified contract into a fetch failure.
        """
        loader = DataLoader()
        loader._fetch_one("rb2601.SHFE", "2024-01-01", "2024-12-31", "1D")

        fake_akshare.futures_zh_daily_sina.assert_called_once_with(symbol="RB2601")

    def test_requested_window_is_applied_to_the_whole_life_frame(
        self, fake_akshare: SimpleNamespace
    ) -> None:
        """The dated endpoint has no date parameters — the slice is ours.

        The stub spans 2024-01-02..2024-01-05; asking for the middle two days
        must return exactly those. Without the slice a one-month request came
        back with the contract's entire history.
        """
        loader = DataLoader()
        df = loader._fetch_one("RB2601", "2024-01-03", "2024-01-04", "1D")

        assert df is not None
        assert [str(d.date()) for d in df.index] == ["2024-01-03", "2024-01-04"]

    def test_main_contract_routes_to_futures_main_sina(
        self, fake_akshare: SimpleNamespace
    ) -> None:
        loader = DataLoader()
        df = loader._fetch_one("RB0", "2024-01-01", "2024-12-31", "1D")

        fake_akshare.futures_main_sina.assert_called_once_with(
            symbol="RB0", start_date="20240101", end_date="20241231",
        )
        fake_akshare.futures_zh_daily_sina.assert_not_called()
        fake_akshare.stock_zh_a_hist.assert_not_called()
        assert df is not None
        # The 价-suffixed names really were mapped, not silently dropped.
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.iloc[0]["close"] == pytest.approx(3104)
        assert df.iloc[0]["open"] == pytest.approx(3135)

    def test_global_contract_returns_none_instead_of_a_share(
        self, fake_akshare: SimpleNamespace
    ) -> None:
        """The #1395 regression, asserted on the call path.

        Sina carries Chinese exchanges only. A global contract must leave the
        loader empty-handed so the chain continues to ``local`` — asserting
        only ``df is None`` would still pass if the A-share endpoint had been
        called and happened to return nothing.
        """
        loader = DataLoader()
        for code in ("CL2412.NYMEX", "ESZ4", "GCM2025.COMEX"):
            fake_akshare.stock_zh_a_hist.reset_mock()
            assert loader._fetch_one(code, "2024-01-01", "2024-12-31", "1D") is None
            fake_akshare.stock_zh_a_hist.assert_not_called()
            fake_akshare.futures_zh_daily_sina.assert_not_called()

    def test_unlisted_contract_is_reported_not_raised(
        self, fake_akshare: SimpleNamespace
    ) -> None:
        """akshare raises for a code Sina does not list (e.g. ``MA605``)."""
        fake_akshare.futures_zh_daily_sina.side_effect = ValueError(
            "Length mismatch: Expected axis has 0 elements"
        )
        loader = DataLoader()
        assert loader._fetch_one("MA605", "2024-01-01", "2024-12-31", "1D") is None

    def test_futures_reject_non_daily_intervals(
        self, fake_akshare: SimpleNamespace
    ) -> None:
        loader = DataLoader()
        with pytest.raises(ValueError, match="daily"):
            loader._fetch_one("RB2601", "2024-01-01", "2024-12-31", "60m")

    def test_a_share_is_untouched_by_the_futures_branch(
        self, fake_akshare: SimpleNamespace
    ) -> None:
        """The other side of the gate: equities must still reach their endpoint."""
        loader = DataLoader()
        loader._fetch_one("600519.SH", "2024-01-01", "2024-12-31", "1D")

        fake_akshare.stock_zh_a_hist.assert_called_once()
        fake_akshare.futures_zh_daily_sina.assert_not_called()
        fake_akshare.futures_main_sina.assert_not_called()
