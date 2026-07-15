"""Regression tests for execution-derived turnover metrics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest.engines.base import BaseEngine
from backtest.engines.china_a import ChinaAEngine
from backtest.engines.composite import CompositeEngine
from backtest.engines.global_futures import GlobalFuturesEngine
from backtest.metrics import calc_metrics, calc_trade_turnover_series


class _RoundedEngine(BaseEngine):
    def can_execute(self, symbol, direction, bar):
        return True

    def round_size(self, raw_size, price):
        return float(int(raw_size))

    def calc_commission(self, size, price, direction, is_open):
        return 0.0

    def apply_slippage(self, price, direction):
        return price


def test_turnover_uses_rounded_fills_instead_of_targets() -> None:
    dates = pd.bdate_range("2026-01-05", periods=2)
    bars = pd.DataFrame({"open": [60.0, 60.0], "close": [60.0, 60.0]}, index=dates)
    close_df = pd.DataFrame({"TEST": bars["close"]}, index=dates)
    targets = pd.DataFrame({"TEST": [0.55, 0.0]}, index=dates)
    engine = _RoundedEngine({"initial_cash": 1_000.0})

    engine._execute_bars(dates, {"TEST": bars}, close_df, targets, ["TEST"])
    equity = pd.Series(
        [snapshot.equity for snapshot in engine.equity_snapshots],
        index=dates,
    )
    turnover = calc_trade_turnover_series(engine.trades, equity)

    # The target asks for 550, but integer sizing fills 9 * 60 = 540.
    assert turnover.tolist() == pytest.approx([0.27, 0.27])
    metrics = calc_metrics(
        equity,
        engine.trades,
        1_000.0,
        positions=targets,
        turnover_series=turnover,
    )
    assert metrics["total_turnover"] == pytest.approx(0.54)
    assert metrics["avg_turnover"] == pytest.approx(0.27)


def test_rejected_target_has_zero_reported_turnover(tmp_path: Path) -> None:
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

    class FakeLoader:
        def fetch(self, *args, **kwargs):
            return {"000001.SZ": bars.copy()}

    class ShortSignal:
        def generate(self, data_map):
            return {"000001.SZ": pd.Series(-1.0, index=dates)}

    engine = ChinaAEngine({"initial_cash": 1_000_000.0})
    metrics = engine.run_backtest(
        {
            "codes": ["000001.SZ"],
            "start_date": "2026-01-05",
            "end_date": "2026-01-07",
            "source": "tushare",
            "initial_cash": 1_000_000.0,
        },
        FakeLoader(),
        ShortSignal(),
        tmp_path,
    )

    # China A-shares reject short opens. The target frame changes, but no fill
    # occurs, so execution-derived turnover must remain zero.
    assert engine.trades == []
    assert metrics["total_turnover"] == 0.0
    assert metrics["avg_turnover"] == 0.0


def test_buy_hold_counts_entry_and_terminal_exit() -> None:
    dates = pd.bdate_range("2026-01-05", periods=3)
    bars = pd.DataFrame({"open": 100.0, "close": 100.0}, index=dates)
    engine = _RoundedEngine({"initial_cash": 1_000.0})
    engine._execute_bars(
        dates,
        {"TEST": bars},
        pd.DataFrame({"TEST": bars["close"]}, index=dates),
        pd.DataFrame({"TEST": [1.0, 1.0, 1.0]}, index=dates),
        ["TEST"],
    )
    equity = pd.Series(
        [snapshot.equity for snapshot in engine.equity_snapshots], index=dates
    )

    turnover = calc_trade_turnover_series(engine.trades, equity)

    assert turnover.tolist() == pytest.approx([0.5, 0.0, 0.5])
    assert turnover.sum() == pytest.approx(1.0)
    assert turnover.mean() == pytest.approx(1.0 / 3.0)


def test_full_rotation_counts_both_executed_legs() -> None:
    dates = pd.bdate_range("2026-01-05", periods=3)
    data_map = {
        code: pd.DataFrame({"open": 100.0, "close": 100.0}, index=dates)
        for code in ("A", "B")
    }
    engine = _RoundedEngine({"initial_cash": 1_000.0})
    engine._execute_bars(
        dates,
        data_map,
        pd.DataFrame({code: frame["close"] for code, frame in data_map.items()}),
        pd.DataFrame({"A": [1.0, 0.0, 0.0], "B": [0.0, 1.0, 1.0]}, index=dates),
        ["A", "B"],
    )
    equity = pd.Series(
        [snapshot.equity for snapshot in engine.equity_snapshots], index=dates
    )

    turnover = calc_trade_turnover_series(engine.trades, equity)

    assert turnover.tolist() == pytest.approx([0.5, 1.0, 0.5])


def test_futures_turnover_uses_multiplier_adjusted_margin() -> None:
    dates = pd.bdate_range("2026-01-05", periods=2)
    symbol = "ESZ4"
    bars = pd.DataFrame(
        {"open": 100.0, "close": 100.0, "pre_close": 100.0}, index=dates
    )
    engine = GlobalFuturesEngine(
        {
            "initial_cash": 1_000_000.0,
            "codes": [symbol],
            "slippage": 0.0,
            "commission_per_contract": 0.0,
        }
    )
    engine._execute_bars(
        dates,
        {symbol: bars},
        pd.DataFrame({symbol: bars["close"]}, index=dates),
        pd.DataFrame({symbol: [0.5, 0.5]}, index=dates),
        [symbol],
    )
    equity = pd.Series(
        [snapshot.equity for snapshot in engine.equity_snapshots], index=dates
    )

    turnover = calc_trade_turnover_series(engine.trades, equity)

    assert turnover.tolist() == pytest.approx([0.25, 0.25])


def test_composite_turnover_uses_each_symbols_margin_contract() -> None:
    dates = pd.bdate_range("2026-01-05", periods=2)
    codes = ["AAPL.US", "ESZ4"]
    data_map = {
        code: pd.DataFrame(
            {"open": 100.0, "close": 100.0, "pre_close": 100.0}, index=dates
        )
        for code in codes
    }
    engine = CompositeEngine(
        {
            "initial_cash": 1_000_000.0,
            "codes": codes,
            "slippage": 0.0,
            "slippage_us": 0.0,
            "commission_per_contract": 0.0,
        },
        codes,
    )
    engine._execute_bars(
        dates,
        data_map,
        pd.DataFrame({code: frame["close"] for code, frame in data_map.items()}),
        pd.DataFrame({"AAPL.US": [0.25, 0.25], "ESZ4": [0.25, 0.25]}, index=dates),
        codes,
    )
    equity = pd.Series(
        [snapshot.equity for snapshot in engine.equity_snapshots], index=dates
    )

    turnover = calc_trade_turnover_series(engine.trades, equity)

    assert turnover.tolist() == pytest.approx([0.25, 0.25])
