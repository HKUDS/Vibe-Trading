"""Tests for fundamental-column enrichment in the SP500 alpha-bench panel.

Pins the wiring added so the ``fundamental`` zoo can run on the US universe:
``_load_sp500_panel`` must attach PIT-safe ``fund:*`` columns (roe,
gross_profitability, asset_growth, net_income, shares_diluted) aligned to the
OHLCV trading-day index, and must degrade to the pre-enrichment panel when the
fundamentals loader fails.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.tools import alpha_bench_tool as abt

FUND_FIELDS = [
    "fund:roe",
    "fund:gross_profitability",
    "fund:asset_growth",
    "fund:net_income",
    "fund:shares_diluted",
]


def _ohlcv(code: str, start: str, end: str) -> pd.DataFrame:
    idx = pd.date_range(start, end, freq="B")
    return pd.DataFrame(
        {"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1e6},
        index=idx,
    )


class _FakeLoader:
    def fetch(self, codes, start, end):
        return {c: _ohlcv(c, start, end) for c in codes}


def _fake_fund_panels(symbols, fields, start, end, freq, pit):
    """Calendar-day fund frames that deliberately differ from the trading-day
    index — the enrichment must reindex onto the OHLCV dates."""
    cal = pd.date_range(start, end, freq="D")
    out = {}
    for f in fields:
        base = 0.2
        out[f] = pd.DataFrame(
            {s: base + i for i, s in enumerate(symbols)}, index=cal
        )
    return out


@pytest.fixture
def wired_env(monkeypatch):
    monkeypatch.setattr(abt, "_fetch_sp500_constituents", lambda: ["AAA", "BBB"])
    import backtest.loaders.registry as reg

    monkeypatch.setattr(reg, "resolve_loader", lambda _market: _FakeLoader())
    import backtest.loaders.fundamentals_loader as fl

    monkeypatch.setattr(fl, "load_fundamental_panel", _fake_fund_panels)


def test_fund_columns_land_aligned_to_trading_index(wired_env):
    panel = abt._load_sp500_panel("2020-01-01", "2020-01-31")

    for key in FUND_FIELDS:
        assert key in panel, f"missing {key}"
        frame = panel[key]
        # aligned onto the OHLCV trading-day index, not the calendar index
        pd.testing.assert_index_equal(frame.index, panel["close"].index)
        # columns match the OHLCV universe
        assert list(frame.columns) == list(panel["close"].columns)
        assert frame.notna().all().all(), f"{key} lost values during reindex"


def test_fund_frames_drop_symbols_absent_from_ohlcv(wired_env, monkeypatch):
    """yahoo occasionally drops tickers; fund frames must shrink to the close
    universe or the registry's shape validation rejects the alpha output."""
    import backtest.loaders.fundamentals_loader as fl

    def extra_symbol(symbols, fields, start, end, freq, pit):
        frames = _fake_fund_panels(symbols, fields, start, end, freq, pit)
        for f in frames:
            frames[f]["CCC"] = 0.5  # not in the OHLCV universe
        return frames

    monkeypatch.setattr(fl, "load_fundamental_panel", extra_symbol)

    panel = abt._load_sp500_panel("2020-01-01", "2020-01-31")

    for key in FUND_FIELDS:
        assert list(panel[key].columns) == list(panel["close"].columns)
        assert "CCC" not in panel[key].columns


def test_fund_enrichment_failure_degrades_gracefully(wired_env, monkeypatch):
    import backtest.loaders.fundamentals_loader as fl

    def boom(*args, **kwargs):
        raise RuntimeError("SEC down")

    monkeypatch.setattr(fl, "load_fundamental_panel", boom)

    panel = abt._load_sp500_panel("2020-01-01", "2020-01-31")

    # OHLCV + vwap still present, no fund keys, no exception
    assert "close" in panel and "vwap" in panel
    assert not any(k.startswith("fund:") for k in panel)


def test_meta_blob_survives_enrichment(wired_env):
    panel = abt._load_sp500_panel("2020-01-01", "2020-01-31")

    assert "_meta" in panel
    assert panel["_meta"]["universe"] == "sp500"
