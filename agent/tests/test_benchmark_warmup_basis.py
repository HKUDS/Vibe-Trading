"""A benchmark is bought at the window's first traded open, like the strategy.

Both start from cash before the first evaluated bar opens, and the engine
fills the strategy at a bar's open. The equal-weight basket used to run from
the previous close: with a warm-up boundary that is a warm-up bar, a price no
position could have been opened at. A declared external benchmark started at
the first evaluated close instead, dropping the first bar's move the strategy
did hold. On a 20/60 SMA run over AAPL.US the basket read 42.54% where
buy-and-hold from the first open was 46.6%, so excess return was overstated.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import backtest.runner as runner
from backtest.benchmark import BenchmarkResult
from backtest.metrics import entry_returns

_DATES = pd.bdate_range("2026-01-05", periods=5)
_STOCK_OPEN = [99.0, 108.0, 115.0, 128.0, 139.0]
_STOCK_CLOSE = [100.0, 110.0, 120.0, 130.0, 140.0]
_BENCH_OPEN = [190.0, 215.0, 230.0, 245.0, 290.0]
_BENCH_CLOSE = [200.0, 220.0, 240.0, 250.0, 300.0]
# Bars 0-1 are warm-up; the window opens at 115 / 230 and closes at 140 / 300.
_EVALUATION_START = str(_DATES[2].date())


def _bars(opens: list[float], closes: list[float], dates=_DATES) -> pd.DataFrame:
    return pd.DataFrame(
        {"open": opens, "high": closes, "low": opens, "close": closes, "volume": [1_000.0] * len(closes)},
        index=dates,
    ).rename_axis("date")


def _run(tmp_path, monkeypatch, *, benchmark=None, warmup=True, frames=None, codes=("AAPL.US",)):
    from backtest.loaders import local_loader

    frames = frames or {
        "AAPL.US": _bars(_STOCK_OPEN, _STOCK_CLOSE),
        "SPY.US": _bars(_BENCH_OPEN, _BENCH_CLOSE),
    }
    sources = []
    for symbol, frame in frames.items():
        path = tmp_path / f"{symbol}.csv"
        frame.to_csv(path)
        sources.append({"symbol": symbol, "type": "csv", "path": str(path)})
    bridge = tmp_path / "bridge.json"
    bridge.write_text(json.dumps({"sources": sources}))
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", bridge)
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    monkeypatch.setenv("VIBE_TRADING_DATA_CACHE", "0")

    class _NoNetwork:
        def fetch(self, *args, **kwargs):
            return {}

    monkeypatch.setattr("backtest.benchmark.YfinanceLoader", _NoNetwork)
    run = tmp_path / "run"
    (run / "code").mkdir(parents=True)
    (run / "code/signal_engine.py").write_text(
        "class SignalEngine:\n"
        "    def generate(self, data_map):\n"
        "        return {code: frame['close'] * 0 for code, frame in data_map.items()}\n"
    )
    config = {
        "codes": list(codes), "source": "local", "initial_cash": 100_000,
        "start_date": str(_DATES[0].date()), "end_date": str(_DATES[-1].date()),
    }
    if warmup:
        config["evaluation_start_date"] = _EVALUATION_START
    if benchmark:
        config["benchmark"] = benchmark
    (run / "config.json").write_text(json.dumps(config))
    runner.main(run)
    card = json.loads((run / "run_card.json").read_text())
    equity = pd.read_csv(run / "artifacts" / "equity.csv")
    return card["metrics"], equity


def test_equal_weight_basket_buys_at_the_first_evaluated_open(tmp_path, monkeypatch):
    metrics, equity = _run(tmp_path, monkeypatch)

    assert metrics["benchmark_kind"] == "equal_weight"
    # From the warm-up close it was 140 / 110 - 1, from the first close 140 / 120 - 1.
    assert metrics["benchmark_return"] == pytest.approx(140 / 115 - 1, abs=1e-6)
    assert equity["timestamp"].iloc[0] == _EVALUATION_START
    assert equity["benchmark_equity"].iloc[0] == pytest.approx(100_000 * 120 / 115)
    # The flat strategy earns nothing, so its excess is minus the benchmark.
    assert metrics["excess_return"] == pytest.approx(-(140 / 115 - 1), abs=1e-6)


def test_external_benchmark_buys_at_its_first_evaluated_open(tmp_path, monkeypatch):
    metrics, equity = _run(tmp_path, monkeypatch, benchmark="SPY.US")

    assert metrics["benchmark_kind"] == "external"
    assert metrics["benchmark_return"] == pytest.approx(300 / 230 - 1, abs=1e-6)
    assert equity["benchmark_equity"].iloc[0] == pytest.approx(100_000 * 240 / 230)
    assert equity["benchmark_equity"].iloc[-1] == pytest.approx(100_000 * 300 / 230)


def test_without_a_warm_up_boundary_the_basket_buys_at_the_first_open(tmp_path, monkeypatch):
    metrics, equity = _run(tmp_path, monkeypatch, warmup=False)

    assert metrics["benchmark_return"] == pytest.approx(140 / 99 - 1, abs=1e-6)
    assert equity["benchmark_equity"].iloc[0] == pytest.approx(100_000 * 100 / 99)


def test_a_symbol_halted_on_the_first_bar_enters_at_its_first_traded_open(tmp_path, monkeypatch):
    halted_dates = _DATES.delete(2)  # MSFT.US has no bar on the first evaluated day
    frames = {
        "AAPL.US": _bars(_STOCK_OPEN, _STOCK_CLOSE),
        "MSFT.US": _bars([49.0, 50.0, 64.0, 70.0], [50.0, 55.0, 65.0, 72.0], dates=halted_dates),
    }
    metrics, equity = _run(tmp_path, monkeypatch, frames=frames, codes=("AAPL.US", "MSFT.US"))

    aapl = [120 / 115 - 1, 130 / 120 - 1, 140 / 130 - 1]
    # MSFT is not bought at its carried warm-up close (55) but at 64, its first open.
    msft = [0.0, 65 / 64 - 1, 72 / 65 - 1]
    expected = np.prod([1 + (a + m) / 2 for a, m in zip(aapl, msft)]) - 1
    assert metrics["benchmark_return"] == pytest.approx(expected, abs=1e-6)


def test_entry_falls_back_to_the_close_without_a_usable_open():
    close = pd.Series([10.0, 11.0, 12.1], index=_DATES[:3])

    for opens in (None, pd.Series([np.nan, 9.0, 9.0], index=_DATES[:3]), pd.Series([0.0, 9.0, 9.0], index=_DATES[:3])):
        ret = entry_returns(close, opens)
        assert ret.tolist() == pytest.approx([0.0, 0.1, 0.1])

    assert entry_returns(pd.Series([np.nan, np.nan], index=_DATES[:2])).tolist() == [0.0, 0.0]


def test_external_total_and_per_bar_returns_agree():
    result = BenchmarkResult(
        ticker="SPY.US", ret_series=pd.Series(dtype=float), total_ret=0.0,
        close=pd.Series(_BENCH_CLOSE, index=_DATES), open=pd.Series(_BENCH_OPEN, index=_DATES),
    )
    window = _DATES[2:]

    total = result.total_return_over(window)
    per_bar = result.returns_over(window)

    assert total == pytest.approx(300 / 230 - 1)
    assert (1 + per_bar).prod() - 1 == pytest.approx(total)
