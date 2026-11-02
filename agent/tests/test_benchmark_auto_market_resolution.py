"""Regression: `benchmark: "auto"` must actually pick a market benchmark.

The engine accepted the `"auto"` sentinel and then skipped benchmark
resolution entirely (`if bench_ticker and bench_ticker != "auto"`), so every
run that asked for automatic selection graded excess_return,
information_ratio, tracking_error and benchmark_beta against the internal
equal-weight basket of the traded symbols instead of a market index. The
inference machinery behind `MARKET_BENCHMARKS` / `_infer_market` was dead
code on that path.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.benchmark import MARKET_BENCHMARKS, _infer_market, resolve_benchmark
from backtest.engines.china_a import ChinaAEngine


class _RecordingLoader:
    """Returns a benchmark frame for whatever ticker is asked for, and
    remembers what was asked."""

    def __init__(self) -> None:
        self.requested: list[str] = []

    def fetch(self, codes, *args, **kwargs):
        self.requested.extend(codes)
        index = pd.date_range("2025-01-01", periods=3)
        return {code: pd.DataFrame({"close": [100.0, 110.0, 121.0]}, index=index) for code in codes}


class _FlatSignal:
    def generate(self, data_map):
        return {code: pd.Series(0.0, index=df.index) for code, df in data_map.items()}


def _bars() -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=3)
    return pd.DataFrame({"close": [10.0, 11.0, 12.1]}, index=index)


# ── inference table ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("PBR.BA", "argentina_equity"),
        ("VNM.VN", "vietnam_equity"),
    ],
)
def test_infer_market_maps_the_suffixes_the_table_could_not_serve(symbol, expected):
    """`.BA` and `.VN` used to fall through to `us_equity`, so an Argentine or
    Vietnamese run was graded against SPY."""
    assert _infer_market([symbol], "yfinance") == expected


def test_every_market_the_inference_can_return_is_a_known_row():
    """`_infer_market` returning a market `MARKET_BENCHMARKS` does not carry
    silently produced no benchmark at all: a `.get()` miss is indistinguishable
    from a deliberate "no universal benchmark"."""
    for market in {
        "us_equity",
        "hk_equity",
        "ca_equity",
        "br_equity",
        "a_share",
        "india_equity",
        "kr_equity",
        "argentina_equity",
        "vietnam_equity",
        "crypto",
        "futures",
        "forex",
    }:
        assert market in MARKET_BENCHMARKS, f"{market} is inferred but has no row"


@pytest.mark.parametrize(
    ("market", "ticker"),
    [
        ("india_equity", "^NSEI"),
        ("kr_equity", "^KS11"),
        ("argentina_equity", "^MERV"),
    ],
)
def test_newly_served_markets_carry_an_index_ticker(market, ticker):
    assert MARKET_BENCHMARKS[market] == ticker


# ── the sentinel has to do something ─────────────────────────────────────


def test_auto_benchmark_resolves_the_market_index_instead_of_the_standin():
    """`benchmark: "auto"` on an A-share run must fetch the CSI 300, not grade
    against an equal-weight basket of the traded symbols."""
    loader = _RecordingLoader()
    index = pd.date_range("2025-01-01", periods=3)

    result = resolve_benchmark(["600000.SH"], "yfinance", "2025-01-01", "2025-01-03", loader=loader)

    assert loader.requested == ["000300.SH"]
    assert result is not None
    assert result.ticker == "000300.SH"
    assert not result.ret_series.empty
    assert result.ret_series.index.equals(index)


def test_auto_sentinel_in_the_engine_config_reaches_the_inference(monkeypatch, tmp_path):
    """The engine must not short-circuit the `"auto"` sentinel before
    resolution. This is the branch that made the inference dead code."""
    seen: dict[str, object] = {}

    def fake_resolve(**kwargs):
        seen["explicit"] = kwargs.get("explicit")
        seen["codes"] = kwargs.get("strategy_codes")
        return None

    monkeypatch.setattr("backtest.benchmark.resolve_benchmark", fake_resolve)

    dates = pd.date_range("2025-01-01", periods=3)
    bars = pd.DataFrame({"close": [10.0, 11.0, 12.1]}, index=dates)

    class Loader:
        def fetch(self, codes, *args, **kwargs):
            return {codes[0]: bars.copy()}

    config = {
        "codes": ["600000.SH"],
        "start_date": str(dates[0].date()),
        "end_date": str(dates[-1].date()),
        "source": "yfinance",
        "initial_cash": 1_000_000.0,
        "benchmark": "auto",
    }
    ChinaAEngine({"initial_cash": 1_000_000.0}).run_backtest(config, Loader(), _FlatSignal(), tmp_path)

    assert seen.get("explicit") is None
    assert seen.get("codes") == ["600000.SH"]


# ── and it must degrade, not break ───────────────────────────────────────


def test_unfetchable_market_benchmark_degrades_to_the_standin(tmp_path):
    """A benchmark ticker the loader cannot supply leaves the run graded
    against the equal-weight basket, which is the documented fallback, and
    the run still completes."""
    dates = pd.date_range("2025-01-01", periods=3)

    class BenchmarklessLoader:
        """Supplies the strategy's own bars and nothing for the index."""

        name = "yfinance"

        def fetch(self, codes, *args, **kwargs):
            out = {}
            for code in codes:
                out[code] = _bars().copy() if code == "600000.SH" else pd.DataFrame()
            return out

    config = {
        "codes": ["600000.SH"],
        "start_date": str(dates[0].date()),
        "end_date": str(dates[-1].date()),
        "source": "yfinance",
        "initial_cash": 1_000_000.0,
        "benchmark": "auto",
    }
    metrics = ChinaAEngine({"initial_cash": 1_000_000.0}).run_backtest(
        config, BenchmarklessLoader(), _FlatSignal(), tmp_path
    )

    assert metrics["total_return"] == pytest.approx(0.0)
