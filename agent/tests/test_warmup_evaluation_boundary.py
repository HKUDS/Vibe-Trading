"""Regression coverage for data warm-up versus evaluation time (#1240)."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest.engines.base import _evaluation_start_for_index
from backtest.engines.global_equity import GlobalEquityEngine
from backtest.engines.options_portfolio import run_options_backtest


class _RecordingLoader:
    name = "fixture"

    def __init__(self, bars: pd.DataFrame) -> None:
        self.bars = bars
        self.calls: list[tuple[str, str]] = []

    def fetch(self, codes, start_date, end_date, **kwargs):
        self.calls.append((start_date, end_date))
        return {codes[0]: self.bars.copy()}


class _WarmSignal:
    def __init__(self) -> None:
        self.seen_dates: pd.DatetimeIndex | None = None

    def generate(self, data_map):
        frame = data_map["AAPL.US"]
        self.seen_dates = frame.index
        return {"AAPL.US": pd.Series(1.0, index=frame.index)}


def _bars() -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    close = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    return pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": [1_000.0] * len(dates),
        },
        index=dates,
    )


def test_evaluation_start_matches_timezone_aware_market_index() -> None:
    dates = pd.date_range("2026-01-01", periods=2, tz="America/New_York")

    start = _evaluation_start_for_index(dates, "2026-01-02")

    assert start == pd.Timestamp("2026-01-02", tz="America/New_York")


def test_warmup_data_reaches_signal_but_not_evaluation_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    bars = _bars()
    loader = _RecordingLoader(bars)
    signal = _WarmSignal()
    benchmark_calls: list[dict] = []

    def fake_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        evaluation_dates = bars.index[bars.index >= pd.Timestamp("2026-01-03")]
        return SimpleNamespace(
            ticker="SPY",
            ret_series=pd.Series(0.0, index=evaluation_dates),
            total_ret=0.0,
        )

    benchmark_module = types.ModuleType("backtest.benchmark")
    benchmark_module.resolve_benchmark = fake_benchmark
    monkeypatch.setitem(sys.modules, "backtest.benchmark", benchmark_module)
    config = {
        "codes": ["AAPL.US"],
        "source": "yfinance",
        "data_start_date": "2026-01-01",
        "start_date": "2026-01-03",
        "end_date": "2026-01-06",
        "initial_cash": 10_000.0,
        "position_adjustment": "hold",
        "slippage_us": 0.0,
        "benchmark": "SPY",
    }

    metrics = GlobalEquityEngine(config, market="us").run_backtest(
        config, loader, signal, tmp_path
    )

    assert loader.calls == [("2026-01-01", "2026-01-06")]
    assert signal.seen_dates is not None
    assert signal.seen_dates[0] == pd.Timestamp("2026-01-01")
    assert benchmark_calls[0]["start_date"] == "2026-01-03"

    equity = pd.read_csv(tmp_path / "artifacts" / "equity.csv")
    positions = pd.read_csv(tmp_path / "artifacts" / "positions.csv")
    targets = pd.read_csv(tmp_path / "artifacts" / "target_positions.csv")
    trades = pd.read_csv(tmp_path / "artifacts" / "trades.csv")

    assert equity["timestamp"].iloc[0].startswith("2026-01-03")
    assert positions["timestamp"].iloc[0].startswith("2026-01-03")
    assert targets["timestamp"].iloc[0].startswith("2026-01-03")
    assert targets["AAPL.US"].iloc[0] == pytest.approx(1.0)
    assert pd.to_datetime(trades["timestamp"]).min() >= pd.Timestamp("2026-01-03")
    assert metrics["benchmark_return"] == pytest.approx(0.0)

    run_card = json.loads((tmp_path / "run_card.json").read_text(encoding="utf-8"))
    assert run_card["backtest"]["data_start_date"] == "2026-01-01"
    assert run_card["backtest"]["start_date"] == "2026-01-03"


def test_options_engine_ignores_warmup_signals(tmp_path) -> None:
    bars = _bars()
    loader = _RecordingLoader(bars)

    class OptionSignals:
        def generate(self, data_map):
            assert data_map["AAPL.US"].index[0] == pd.Timestamp("2026-01-01")
            leg = {"type": "call", "strike": 100.0, "expiry": "2026-03-20", "qty": 1}
            return [
                {
                    "date": "2026-01-02",
                    "action": "open",
                    "underlying": "AAPL.US",
                    "legs": [leg],
                },
                {
                    "date": "2026-01-03",
                    "action": "open",
                    "underlying": "AAPL.US",
                    "legs": [leg],
                },
            ]

    run_options_backtest(
        {
            "codes": ["AAPL.US"],
            "source": "yfinance",
            "engine": "options",
            "data_start_date": "2026-01-01",
            "start_date": "2026-01-03",
            "end_date": "2026-01-06",
            "initial_cash": 10_000.0,
        },
        loader,
        OptionSignals(),
        tmp_path,
    )

    assert loader.calls == [("2026-01-01", "2026-01-06")]
    equity = pd.read_csv(tmp_path / "artifacts" / "equity.csv")
    trades = pd.read_csv(tmp_path / "artifacts" / "trades.csv")
    assert equity["timestamp"].iloc[0] == "2026-01-03"
    assert trades["timestamp"].min() == "2026-01-03"


def test_implicit_benchmark_does_not_inherit_warmup_return(tmp_path) -> None:
    bars = _bars()
    config = {
        "codes": ["AAPL.US"],
        "source": "yfinance",
        "data_start_date": "2026-01-01",
        "start_date": "2026-01-03",
        "end_date": "2026-01-06",
        "initial_cash": 10_000.0,
        "position_adjustment": "hold",
        "slippage_us": 0.0,
    }

    GlobalEquityEngine(config, market="us").run_backtest(
        config, _RecordingLoader(bars), _WarmSignal(), tmp_path
    )

    equity = pd.read_csv(tmp_path / "artifacts" / "equity.csv")
    assert equity["benchmark_equity"].iloc[0] == pytest.approx(10_000.0)
