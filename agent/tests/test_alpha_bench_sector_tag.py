"""Tests for sector-tag enrichment in the SP500 alpha-bench panel.

Pins the wiring so the 19 requires_sector=True alpha101 alphas can run on
the US universe: ``_load_sp500_panel`` must attach a same-shape ``sector``
DataFrame of per-code sector labels, and must degrade gracefully when the
sector fetch fails.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.tools import alpha_bench_tool as abt


def _ohlcv(code: str, start: str, end: str) -> pd.DataFrame:
    idx = pd.date_range(start, end, freq="B")
    return pd.DataFrame(
        {"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1e6},
        index=idx,
    )


class _FakeLoader:
    def fetch(self, codes, start, end):
        return {c: _ohlcv(c, start, end) for c in codes}


@pytest.fixture
def wired_env(monkeypatch):
    monkeypatch.setattr(abt, "_fetch_sp500_constituents", lambda: ["AAA", "BBB"])
    import yfinance as yf

    class _FakeTicker:
        @property
        def info(self):
            return {"sector": "Technology"}

    monkeypatch.setattr(yf, "Ticker", lambda code: _FakeTicker())
    import backtest.loaders.registry as reg

    monkeypatch.setattr(reg, "resolve_loader", lambda _market: _FakeLoader())


def test_sector_dataframe_attached_same_shape(wired_env, monkeypatch):
    monkeypatch.setattr(
        abt,
        "_fetch_sp500_constituents",
        lambda: ["AAPL", "JPM"],
    )

    panel = abt._load_sp500_panel("2020-01-01", "2020-01-31")

    assert "sector" in panel, "sector key missing from panel"
    sec = panel["sector"]
    assert isinstance(sec, pd.DataFrame)
    pd.testing.assert_index_equal(sec.index, panel["close"].index)
    assert list(sec.columns) == list(panel["close"].columns)


def test_sector_enrichment_failure_degrades_gracefully(wired_env, monkeypatch):
    import yfinance as yf

    def boom(*args, **kwargs):
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(yf, "Ticker", lambda code: type("_T", (), {"info": boom})())

    panel = abt._load_sp500_panel("2020-01-01", "2020-01-31")

    assert "sector" not in panel
    assert "close" in panel and "vwap" in panel


def test_meta_blob_survives_enrichment(wired_env):
    panel = abt._load_sp500_panel("2020-01-01", "2020-01-31")

    assert "_meta" in panel
    assert panel["_meta"]["universe"] == "sp500"


def test_no_sector_when_yfinance_returns_none(wired_env, monkeypatch):
    import yfinance as yf

    class _FakeTicker:
        @property
        def info(self):
            return {"sector": None}

    monkeypatch.setattr(yf, "Ticker", lambda code: _FakeTicker())

    panel = abt._load_sp500_panel("2020-01-01", "2020-01-31")

    assert "sector" not in panel
