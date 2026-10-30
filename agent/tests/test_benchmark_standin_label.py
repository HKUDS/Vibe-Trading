"""Regression (#2123): the fallback benchmark must never masquerade as an index.

When ``config["benchmark"]`` is absent the engine grades every benchmark
relative metric against the internally built equal-weight basket of the traded
symbols. For a single-symbol run that basket is the instrument itself, so
``benchmark_return`` / ``excess_return`` become "timing vs buy-and-hold" while
still wearing an index-sounding field name, with zero warning (#2123).

The fix keeps the numbers but stops hiding what they are graded against: it
emits an explicit ``benchmark_ticker`` stand-in marker unconditionally (so the
``metrics.csv`` schema no longer shifts per run) and surfaces a warning naming
the stand-in whenever the reference is not an external index.
"""

from __future__ import annotations

import json

import pandas as pd

from backtest.benchmark import BenchmarkResult
from backtest.engines.china_a import ChinaAEngine
from backtest.metrics import bar_returns, buy_and_hold_return


class _FakeLoader:
    def __init__(self, bars: pd.DataFrame, codes: list[str]) -> None:
        self._bars = bars
        self._codes = codes

    def fetch(self, *args, **kwargs):
        return {code: self._bars.copy() for code in self._codes}


class _FlatSignal:
    """Zero position throughout: equity stays exactly at initial_cash."""

    def generate(self, data_map):
        return {code: pd.Series(0.0, index=df.index) for code, df in data_map.items()}


def _bars(dates: pd.DatetimeIndex) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "open": [10.0] * n,
            "high": [10.0] * n,
            "low": [10.0] * n,
            "close": [10.0] * n,
            "volume": [1_000] * n,
        },
        index=dates,
    )


def _config(codes: list[str], dates: pd.DatetimeIndex, benchmark: str | None = None) -> dict:
    cfg = {
        "codes": codes,
        "start_date": str(dates[0].date()),
        "end_date": str(dates[-1].date()),
        "source": "tushare",
        "initial_cash": 1_000_000.0,
    }
    if benchmark is not None:
        cfg["benchmark"] = benchmark
    return cfg


def _run_card_warnings(run_dir) -> str:
    payload = json.loads((run_dir / "run_card.json").read_text())
    return " || ".join(payload.get("warnings", []))


def test_no_benchmark_single_symbol_marks_standin_and_warns(tmp_path):
    dates = pd.bdate_range("2026-01-05", periods=3)
    bars = _bars(dates)
    config = _config(["000001.SZ"], dates)

    engine = ChinaAEngine({"initial_cash": 1_000_000.0})
    metrics = engine.run_backtest(config, _FakeLoader(bars, ["000001.SZ"]), _FlatSignal(), tmp_path)

    # Explicit marker: benchmark_ticker is emitted even with no benchmark, and
    # it names the stand-in instead of leaving the field under an index name.
    ticker = metrics.get("benchmark_ticker")
    assert isinstance(ticker, str) and ticker
    assert "(stand-in)" in ticker
    # Single-symbol degenerates to the instrument's own buy-and-hold: say so.
    assert "buy-and-hold" in ticker
    assert "000001.SZ" in ticker

    # The warning must surface on the run card, not stay silent.
    warn_text = _run_card_warnings(tmp_path)
    assert "not an external index" in warn_text
    assert "(stand-in)" in warn_text


def test_no_benchmark_multisymbol_labels_basket(tmp_path):
    dates = pd.bdate_range("2026-01-05", periods=3)
    bars = _bars(dates)
    codes = ["000001.SZ", "000002.SZ"]
    config = _config(codes, dates)

    engine = ChinaAEngine({"initial_cash": 1_000_000.0})
    metrics = engine.run_backtest(config, _FakeLoader(bars, codes), _FlatSignal(), tmp_path)

    ticker = metrics.get("benchmark_ticker")
    assert isinstance(ticker, str) and ticker
    assert "(stand-in)" in ticker
    assert "basket" in ticker
    assert "2" in ticker


def test_declared_resolved_benchmark_has_no_standin_marker(monkeypatch, tmp_path):
    dates = pd.bdate_range("2026-01-05", periods=3)
    bars = _bars(dates)
    config = _config(["000001.SZ"], dates, benchmark="BENCH")

    bench_close = pd.Series([100.0, 105.0, 110.0], index=dates)
    fake_result = BenchmarkResult(
        ticker="BENCH",
        ret_series=bar_returns(bench_close, label="test-benchmark"),
        total_ret=buy_and_hold_return(bench_close),
        close=bench_close,
    )
    monkeypatch.setattr(
        "backtest.benchmark.resolve_benchmark", lambda **kwargs: fake_result
    )

    engine = ChinaAEngine({"initial_cash": 1_000_000.0})
    metrics = engine.run_backtest(config, _FakeLoader(bars, ["000001.SZ"]), _FlatSignal(), tmp_path)

    # A real, resolved benchmark keeps its own ticker and must not be relabelled
    # as a stand-in, and must not raise the stand-in warning.
    assert metrics.get("benchmark_ticker") == "BENCH"
    assert "(stand-in)" not in str(metrics.get("benchmark_ticker", ""))
    warn_text = _run_card_warnings(tmp_path)
    assert "(stand-in)" not in warn_text
