"""Regression: excess_return must stay consistent with the corrected
benchmark_return once an external benchmark's price series crosses a
non-positive-prior-price bar.

BaseEngine.run_backtest() overwrites the internally-computed benchmark_return
with the #872-safe price relative (BenchmarkResult.total_ret), but never
re-derived excess_return from that same corrected value, so the two fields
went inconsistent with each other in the same metrics dict.
"""

from __future__ import annotations

import pandas as pd
import pytest
import yaml

from backtest.benchmark import BenchmarkResult
from backtest.engines.china_a import ChinaAEngine
from backtest.loaders import local_loader
from backtest.metrics import bar_returns, buy_and_hold_return
from backtest.runner import _AutoLoader, fetch_data_map


class _FakeLoader:
    def __init__(self, bars: pd.DataFrame) -> None:
        self._bars = bars

    def fetch(self, *args, **kwargs):
        return {"000001.SZ": self._bars.copy()}


class _FlatSignal:
    """Zero position throughout: equity stays exactly at initial_cash, so
    total_return is 0.0."""

    def generate(self, data_map):
        return {code: pd.Series(0.0, index=df.index) for code, df in data_map.items()}


def _config(tmp_path, dates: pd.DatetimeIndex) -> dict:
    return {
        "codes": ["000001.SZ"],
        "start_date": str(dates[0].date()),
        "end_date": str(dates[-1].date()),
        "source": "tushare",
        "initial_cash": 1_000_000.0,
        "benchmark": "BENCH",
    }


def test_excess_return_matches_corrected_benchmark_return(monkeypatch, tmp_path):
    dates = pd.bdate_range("2026-01-05", periods=4)
    bars = pd.DataFrame(
        {
            "open": [10.0, 10.0, 10.0, 10.0],
            "high": [10.0, 10.0, 10.0, 10.0],
            "low": [10.0, 10.0, 10.0, 10.0],
            "close": [10.0, 10.0, 10.0, 10.0],
            "volume": [1_000, 1_000, 1_000, 1_000],
        },
        index=dates,
    )

    # Benchmark price series with a non-positive-prior-price bar: a
    # suspended/zero-printed bar mid-series, the exact hazard class #872
    # already treats as real (China A-share suspended constituents, vendor
    # glitches). True buy-and-hold return over this series is -50%.
    bench_close = pd.Series([100.0, 100.0, 0.0, 50.0], index=dates)
    fake_result = BenchmarkResult(
        ticker="BENCH",
        ret_series=bar_returns(bench_close, label="test-benchmark"),
        total_ret=buy_and_hold_return(bench_close),
        close=bench_close,
    )
    assert fake_result.total_ret == pytest.approx(-0.5)

    monkeypatch.setattr(
        "backtest.benchmark.resolve_benchmark", lambda **kwargs: fake_result
    )

    engine = ChinaAEngine({"initial_cash": 1_000_000.0})
    metrics = engine.run_backtest(
        _config(tmp_path, dates), _FakeLoader(bars), _FlatSignal(), tmp_path
    )

    # No trades executed, so the strategy's own total_return is exactly 0.0,
    # independent of anything benchmark-related.
    assert metrics["total_return"] == pytest.approx(0.0)

    # benchmark_return is already corrected to the true price relative.
    assert metrics["benchmark_return"] == pytest.approx(-0.5)

    # excess_return must be derived from that same corrected value
    # (0.0 - (-0.5) == 0.5), not from the stale (1 + bench_ret).prod() - 1
    # compounded product, which would silently read 1.0 here instead.
    assert metrics["excess_return"] == pytest.approx(0.5)
    assert metrics["total_return"] - metrics["excess_return"] == pytest.approx(
        metrics["benchmark_return"]
    )


def test_excess_return_unaffected_when_no_external_benchmark(tmp_path):
    """Only the loaded symbol contributes to the unconfigured reference."""
    dates = pd.bdate_range("2026-01-05", periods=3)
    bars = pd.DataFrame(
        {
            "open": [10.0, 10.0, 10.0],
            "high": [10.0, 10.0, 10.0],
            "low": [10.0, 10.0, 10.0],
            "close": [10.0, 10.0, 10.0],
            "volume": [1_000, 1_000, 1_000],
        },
        index=dates,
    )
    config = {
        "codes": ["000002.SZ", "000001.SZ"],
        "start_date": str(dates[0].date()),
        "end_date": str(dates[-1].date()),
        "source": "tushare",
        "initial_cash": 1_000_000.0,
    }

    engine = ChinaAEngine({"initial_cash": 1_000_000.0})
    metrics = engine.run_backtest(config, _FakeLoader(bars), _FlatSignal(), tmp_path)

    assert metrics["benchmark_kind"] == "equal_weight"
    assert "benchmark_ticker" not in metrics
    assert metrics["benchmark_label"] == "equal-weight basket (000001.SZ)"
    assert metrics["excess_return"] == pytest.approx(0.0)


def test_signed_price_policy_applies_to_the_lazily_loaded_benchmark(monkeypatch, tmp_path):
    dates = pd.bdate_range("2026-01-05", periods=4)
    sources = []
    for symbol, prices in (("000001.SZ", [10.0] * 4), ("BENCH", [10.0, -2.0, -3.0, -5.0])):
        csv_path = tmp_path / f"{symbol}.csv"
        pd.DataFrame(
            {
                "date": dates,
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [1_000] * 4,
            }
        ).to_csv(csv_path, index=False)
        sources.append({"symbol": symbol, "type": "csv", "path": str(csv_path)})
    config_path = tmp_path / "data.yaml"
    config_path.write_text(yaml.safe_dump({"sources": sources}), encoding="utf-8")
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", config_path)

    def run(label: str, allow: bool):
        run_dir = tmp_path / label
        run_dir.mkdir()
        config = _config(run_dir, dates) | {"source": "local", "allow_nonpositive_prices": allow}
        fetched = fetch_data_map(config)
        assert set(fetched.data_map) == {"000001.SZ"}
        loader = _AutoLoader(fetched.data_map, inner=fetched.loader, name="local")
        return ChinaAEngine(config).run_backtest(config, loader, _FlatSignal(), run_dir)

    assert run("strict-before", False)["benchmark_kind"] == "equal_weight"
    signed = run("signed", True)
    assert signed["benchmark_kind"] == "external"
    assert signed["benchmark_ticker"] == "BENCH"
    assert signed["benchmark_return"] == pytest.approx(-1.5)
    assert signed["excess_return"] == pytest.approx(1.5)
    assert run("strict-after", False)["benchmark_kind"] == "equal_weight"
