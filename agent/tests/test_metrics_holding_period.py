"""Zero-bar completed trades belong in the average holding-period sample."""

from dataclasses import replace

import pandas as pd
import pytest

from backtest.engines.crypto import CryptoEngine
from backtest.metrics import calc_metrics, win_rate_and_stats
from backtest.models import Position, TradeRecord


def _trade(holding_bars: float) -> TradeRecord:
    return TradeRecord(
        symbol="BTCUSDT",
        direction=1,
        entry_price=100,
        exit_price=100,
        entry_time=pd.Timestamp("2026-01-01"),
        exit_time=pd.Timestamp("2026-01-02"),
        size=1,
        leverage=1,
        pnl=0,
        pnl_pct=0,
        exit_reason="signal",
        holding_bars=holding_bars,
        commission=0,
    )


@pytest.mark.parametrize(
    "durations, expected",
    [
        ([0, 10], 5.0),
        ([0, 0, 9], 3.0),
        ([0, 1.5], 0.8),
        ([0, 0], 0.0),
        ([5, 10, 15], 10.0),
        ([-1, 0, 10], 5.0),
        ([], 0.0),
    ],
)
def test_average_uses_all_nonnegative_holding_periods(durations, expected) -> None:
    trades = [_trade(value) for value in durations]

    assert win_rate_and_stats(trades)["avg_holding_bars"] == expected
    equity = pd.Series([1000.0, 1010.0], index=pd.date_range("2026-01-01", periods=2))
    # Preserve the existing compatibility key; its input is measured in bars.
    assert calc_metrics(equity, trades, 1000.0)["avg_holding_days"] == expected


def test_engine_zero_bar_close_counts_in_average() -> None:
    engine = CryptoEngine({"initial_cash": 1000.0})
    opened = pd.Timestamp("2026-01-01")
    position = Position(
        symbol="BTCUSDT",
        direction=1,
        entry_price=100,
        entry_time=opened,
        size=1,
        entry_bar_idx=0,
    )
    engine.positions["BTCUSDT"] = position
    engine._bar_idx = 0
    engine._close_position("BTCUSDT", 100.0, opened, "end_of_backtest")
    engine.positions["BTCUSDT"] = replace(
        position, entry_time=pd.Timestamp("2026-01-02")
    )
    engine._bar_idx = 10
    engine._close_position("BTCUSDT", 100.0, pd.Timestamp("2026-01-12"), "signal")

    assert [trade.holding_bars for trade in engine.trades] == [0.0, 10.0]
    assert win_rate_and_stats(engine.trades)["avg_holding_bars"] == 5.0
