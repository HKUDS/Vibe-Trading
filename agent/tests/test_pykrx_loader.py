"""Tests for pykrx_loader: symbol mapping, interval contract, normalization.

Unit-level only — no network access and no real ``pykrx`` dependency: the
normalization path is exercised through ``_normalize`` with synthetic
pykrx-shaped frames (Korean column names, date index), and ``_fetch_one`` is
driven through a fake ``pykrx.stock`` module injected into ``sys.modules``.

A live canary against the real package/endpoint lives in
``test_pykrx_live_canary`` and is skipped unless ``VIBE_TRADING_LIVE_PYKRX=1``,
because mocked tests cannot see upstream login-policy or endpoint changes.
"""

from __future__ import annotations

import os
import sys
import types

import pandas as pd
import pytest

from backtest.loaders import pykrx_loader as mod
from backtest.loaders.pykrx_loader import DataLoader, _normalize, map_symbol


class TestMapSymbol:
    """``005930.KS`` / ``247540.KQ`` -> bare 6-digit pykrx ticker."""

    def test_kospi_suffix_stripped(self) -> None:
        assert map_symbol("005930.KS") == "005930"

    def test_kosdaq_suffix_stripped(self) -> None:
        assert map_symbol("247540.KQ") == "247540"

    def test_case_and_whitespace(self) -> None:
        assert map_symbol(" 005930.ks ") == "005930"


def _pykrx_frame() -> pd.DataFrame:
    """Synthetic frame in pykrx's native shape (Korean columns, date index)."""
    idx = pd.to_datetime(["2024-04-02", "2024-04-01"])  # deliberately unsorted
    return pd.DataFrame(
        {
            "시가": [102.0, 100.0],
            "고가": [103.0, 101.0],
            "저가": [101.0, 99.0],
            "종가": [102.5, 100.5],
            "거래량": [20_000, 10_000],
            "등락률": [1.99, 0.5],  # extra pykrx column: must be dropped
        },
        index=idx,
    )


class TestNormalize:
    def test_renames_sorts_and_selects_ohlcv(self) -> None:
        out = _normalize(_pykrx_frame())
        assert out is not None
        assert list(out.columns) == ["open", "high", "low", "close", "volume"]
        assert out.index.name == "trade_date"
        assert out.index.is_monotonic_increasing
        assert out["close"].iloc[-1] == 102.5
        assert all(dtype.kind == "f" for dtype in out.dtypes)

    def test_none_and_empty_input(self) -> None:
        assert _normalize(None) is None
        assert _normalize(pd.DataFrame()) is None

    def test_missing_columns_rejected(self) -> None:
        frame = _pykrx_frame().drop(columns=["종가"])
        assert _normalize(frame) is None

    def test_all_nan_price_rows_dropped(self) -> None:
        frame = _pykrx_frame()
        frame.loc[:, ["시가", "고가", "저가", "종가"]] = float("nan")
        assert _normalize(frame) is None


class _FakeStock:
    """Stand-in for ``pykrx.stock`` recording every OHLCV request."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_market_ohlcv_by_date(self, fromdate, todate, ticker, **kwargs):
        self.calls.append(
            {"fromdate": fromdate, "todate": todate, "ticker": ticker, **kwargs}
        )
        return _pykrx_frame()


@pytest.fixture
def fake_pykrx(monkeypatch: pytest.MonkeyPatch) -> _FakeStock:
    """Inject a fake ``pykrx`` package and neutralise the request throttle."""
    stock = _FakeStock()
    package = types.ModuleType("pykrx")
    package.stock = stock  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pykrx", package)
    monkeypatch.setitem(sys.modules, "pykrx.stock", stock)
    monkeypatch.setattr(mod, "_min_interval", lambda: 0.0)
    return stock


class TestFetchContract:
    def test_daily_fetch_passes_bare_ticker_and_adjusted_flag(
        self, fake_pykrx: _FakeStock
    ) -> None:
        out = DataLoader().fetch(["005930.KS"], "2024-04-01", "2024-04-30")
        assert list(out) == ["005930.KS"]
        assert list(out["005930.KS"].columns) == [
            "open", "high", "low", "close", "volume",
        ]
        call = fake_pykrx.calls[0]
        assert call["ticker"] == "005930"
        assert (call["fromdate"], call["todate"]) == ("20240401", "20240430")
        # Naver-backed adjusted path is requested explicitly, never inherited.
        assert call["adjusted"] is True

    @pytest.mark.parametrize("interval", ["1D", "1d", "d", "day", "daily"])
    def test_daily_aliases_accepted(
        self, fake_pykrx: _FakeStock, interval: str
    ) -> None:
        out = DataLoader().fetch(
            ["005930.KS"], "2024-04-01", "2024-04-30", interval=interval
        )
        assert list(out) == ["005930.KS"]

    @pytest.mark.parametrize("interval", ["1m", "5m", "30m", "1H", "4h", "1W"])
    def test_unsupported_interval_does_not_silently_fetch_daily(
        self, fake_pykrx: _FakeStock, interval: str
    ) -> None:
        """A 1m/1H/4H request must fall through to another source, not day bars."""
        assert DataLoader().fetch(
            ["005930.KS"], "2024-04-01", "2024-04-30", interval=interval
        ) == {}
        assert fake_pykrx.calls == []

    def test_one_bad_symbol_does_not_abort_the_batch(
        self, monkeypatch: pytest.MonkeyPatch, fake_pykrx: _FakeStock
    ) -> None:
        def _boom(fromdate, todate, ticker, **kwargs):
            if ticker == "000000":
                raise RuntimeError("delisted")
            return _pykrx_frame()

        monkeypatch.setattr(fake_pykrx, "get_market_ohlcv_by_date", _boom)
        out = DataLoader().fetch(
            ["000000.KQ", "005930.KS"], "2024-04-01", "2024-04-30"
        )
        assert list(out) == ["005930.KS"]


class TestThrottle:
    def test_requests_are_spaced_through_the_shared_gate(
        self, monkeypatch: pytest.MonkeyPatch, fake_pykrx: _FakeStock
    ) -> None:
        """Spacing must go through the lock-protected HostThrottle, not a global."""
        waits: list[tuple[str, float]] = []
        monkeypatch.setattr(
            mod._THROTTLE, "wait", lambda bucket, interval: waits.append((bucket, interval))
        )
        monkeypatch.setattr(mod, "_min_interval", lambda: 1.0)
        DataLoader().fetch(["005930.KS", "247540.KQ"], "2024-04-01", "2024-04-30")
        assert waits == [("pykrx", 1.0), ("pykrx", 1.0)]

    def test_default_interval_respects_upstream_guidance(self) -> None:
        # pykrx's README asks for ~1s between bulk requests.
        assert mod._DEFAULT_MIN_INTERVAL_S >= 1.0
        assert mod._min_interval() >= 1.0


class TestProvenance:
    def test_unavailable_pykrx_is_not_reported_as_the_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A run card must name the loader that served, never the one requested.

        With the optional package missing, the kr_equity chain resolves to
        Yahoo; recording ``pykrx`` would claim data pykrx never returned.
        """
        from backtest import runner
        from backtest.loaders import yahoo_loader

        frame = pd.DataFrame(
            {"open": [100.0], "high": [101.0], "low": [99.0],
             "close": [100.5], "volume": [1_000.0]},
            index=pd.DatetimeIndex([pd.Timestamp("2024-04-01")], name="trade_date"),
        )
        monkeypatch.setattr(DataLoader, "is_available", lambda self: False)
        monkeypatch.setattr(
            yahoo_loader.DataLoader,
            "fetch",
            lambda self, codes, start, end, **kw: {c: frame.copy() for c in codes},
        )

        result = runner.fetch_data_map(
            {
                "codes": ["005930.KS"],
                "start_date": "2024-04-01",
                "end_date": "2024-04-30",
                "source": "pykrx",
            }
        )
        assert list(result.data_map) == ["005930.KS"]
        assert result.effective_sources == ["yahoo"]

    def test_auto_routing_reports_the_loader_that_served(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same guarantee on the ``source="auto"`` path (symbol-pattern head)."""
        from backtest import runner
        from backtest.loaders import yahoo_loader

        frame = pd.DataFrame(
            {"open": [100.0], "high": [101.0], "low": [99.0],
             "close": [100.5], "volume": [1_000.0]},
            index=pd.DatetimeIndex([pd.Timestamp("2024-04-01")], name="trade_date"),
        )
        monkeypatch.setattr(DataLoader, "is_available", lambda self: False)
        monkeypatch.setattr(
            yahoo_loader.DataLoader,
            "fetch",
            lambda self, codes, start, end, **kw: {c: frame.copy() for c in codes},
        )

        result = runner.fetch_data_map(
            {
                "codes": ["005930.KS"],
                "start_date": "2024-04-01",
                "end_date": "2024-04-30",
                "source": "auto",
            }
        )
        # _detect_source maps .KS -> pykrx, which is exactly the stale guess.
        assert runner._detect_source("005930.KS") == "pykrx"
        assert result.effective_sources == ["yahoo"]


_skip_live = os.getenv("VIBE_TRADING_LIVE_PYKRX", "") != "1"


@pytest.mark.skipif(
    _skip_live,
    reason="live canary: set VIBE_TRADING_LIVE_PYKRX=1 (needs pykrx + network)",
)
def test_pykrx_live_canary() -> None:
    """Opt-in: real pykrx call, so upstream endpoint/login drift is detectable."""
    pytest.importorskip("pykrx")
    out = DataLoader().fetch(["005930.KS"], "2026-07-01", "2026-07-10")
    frame = out.get("005930.KS")
    assert frame is not None and not frame.empty
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert (frame["high"] >= frame["low"]).all()
