"""Regression tests for end-of-backtest liquidation accounting."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engines.base import BaseEngine
from backtest.engines.china_futures import ChinaFuturesEngine
from backtest.engines.composite import CompositeEngine
from backtest.engines.global_futures import GlobalFuturesEngine


class _TerminalCostEngine(BaseEngine):
    def can_execute(self, symbol, direction, bar):
        return True

    def round_size(self, raw_size, price):
        return raw_size

    def calc_commission(self, size, price, direction, is_open):
        return 0.0 if is_open else 7.0

    def apply_slippage(self, price, direction):
        return price + direction if self.positions else price


def test_composite_routes_futures_rules_by_submarket() -> None:
    engine = CompositeEngine(
        {"initial_cash": 1_000_000, "codes": ["IF2406.CFFEX", "ESZ4"]},
        ["IF2406.CFFEX", "ESZ4"],
    )

    assert isinstance(engine._rule_for("IF2406.CFFEX"), ChinaFuturesEngine)
    assert isinstance(engine._rule_for("ESZ4"), GlobalFuturesEngine)
    assert engine._calc_raw_size("ESZ4", 500_000.0, 5_000.0) == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("target_weight", "expected_exit"),
    [(0.5, 99.0), (-0.5, 101.0)],
)
def test_terminal_close_costs_reach_final_equity(
    target_weight: float,
    expected_exit: float,
) -> None:
    dates = pd.DatetimeIndex(["2026-01-05"])
    bars = pd.DataFrame({"open": [100.0], "close": [100.0]}, index=dates)
    close_df = pd.DataFrame({"TEST": bars["close"]}, index=dates)
    target_pos = pd.DataFrame({"TEST": [target_weight]}, index=dates)
    engine = _TerminalCostEngine({"initial_cash": 1_000.0})

    engine._execute_bars(
        dates,
        {"TEST": bars},
        close_df,
        target_pos,
        ["TEST"],
    )

    assert len(engine.trades) == 1
    trade = engine.trades[0]
    assert trade.exit_reason == "end_of_backtest"
    assert trade.exit_price == expected_exit
    assert trade.commission == 7.0
    assert engine.capital == pytest.approx(988.0)

    final_snapshot = engine.equity_snapshots[-1]
    assert final_snapshot.capital == pytest.approx(engine.capital)
    assert final_snapshot.equity == pytest.approx(engine.capital)
    assert final_snapshot.unrealized == 0.0
    assert final_snapshot.positions == 0


@pytest.mark.parametrize(
    ("engine_cls", "symbol"),
    [
        (ChinaFuturesEngine, "IF2406.CFFEX"),
        (GlobalFuturesEngine, "ESZ4"),
    ],
)
@pytest.mark.parametrize("target_weight", [0.25, -0.25])
def test_futures_terminal_close_uses_multiplier_fees_and_exit_slippage(
    engine_cls: type[BaseEngine], symbol: str, target_weight: float
) -> None:
    dates = pd.DatetimeIndex(["2026-01-05"])
    bars = pd.DataFrame(
        {"open": [100.0], "close": [100.0], "pre_close": [100.0]},
        index=dates,
    )
    config = {"initial_cash": 1_000_000.0, "codes": [symbol]}
    engine = engine_cls(config)

    engine._execute_bars(
        dates,
        {symbol: bars},
        pd.DataFrame({symbol: bars["close"]}, index=dates),
        pd.DataFrame({symbol: [target_weight]}, index=dates),
        [symbol],
    )

    trade = engine.trades[0]
    expected_exit = engine.apply_slippage(100.0, -trade.direction)
    assert trade.exit_reason == "end_of_backtest"
    assert trade.exit_price == pytest.approx(expected_exit)
    assert trade.pnl == pytest.approx(
        engine._calc_pnl(
            symbol,
            trade.direction,
            trade.size,
            trade.entry_price,
            trade.exit_price,
        )
    )
    assert trade.commission > 0.0
    assert engine.capital == pytest.approx(
        config["initial_cash"] + trade.pnl - trade.commission
    )
    assert engine.equity_snapshots[-1].equity == pytest.approx(engine.capital)


def test_composite_terminal_close_routes_costs_per_symbol() -> None:
    dates = pd.DatetimeIndex(["2026-01-05"])
    codes = ["AAPL.US", "ESZ4"]
    data_map = {
        code: pd.DataFrame(
            {"open": [100.0], "close": [100.0], "pre_close": [100.0]},
            index=dates,
        )
        for code in codes
    }
    close_df = pd.DataFrame(
        {code: data_map[code]["close"] for code in codes}, index=dates
    )
    target_pos = pd.DataFrame(
        {"AAPL.US": [0.2], "ESZ4": [0.2]}, index=dates
    )
    config = {"initial_cash": 1_000_000.0, "codes": codes}
    engine = CompositeEngine(config, codes)

    engine._execute_bars(dates, data_map, close_df, target_pos, codes)

    trades = {trade.symbol: trade for trade in engine.trades}
    assert set(trades) == set(codes)
    assert trades["AAPL.US"].commission == 0.0
    assert trades["ESZ4"].commission > 0.0
    for symbol, trade in trades.items():
        sub_engine = engine._rule_for(symbol)
        sub_engine._active_symbol = symbol
        assert trade.exit_price == pytest.approx(
            sub_engine.apply_slippage(100.0, -trade.direction)
        )
    assert engine.capital == pytest.approx(
        config["initial_cash"]
        + sum(trade.pnl - trade.commission for trade in trades.values())
    )
    assert engine.equity_snapshots[-1].equity == pytest.approx(engine.capital)
