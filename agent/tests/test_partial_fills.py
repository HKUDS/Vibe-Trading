"""Adversarial tests for persistent orders and partial-fill accounting."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backtest.engines.base import BaseEngine
from backtest.metrics import calc_execution_metrics
from backtest.models import OrderRecord
from backtest.reporting import build_reporting_outputs


class PartialFillEngine(BaseEngine):
    """Deterministic engine with a configurable per-call fill schedule."""

    def __init__(self, config: dict, fill_schedule: list[float] | None = None):
        super().__init__(config)
        self.fill_schedule = list(fill_schedule or [])

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        return round(max(float(raw_size), 0.0), 8)

    def calc_commission(
        self,
        size: float,
        price: float,
        direction: int,
        is_open: bool,
    ) -> float:
        return round(abs(size * price) * 0.001, 8)

    def apply_slippage(self, price: float, direction: int) -> float:
        return float(price) + 0.1 * direction

    def determine_fill_quantity(
        self,
        order: OrderRecord,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> float:
        if self.fill_schedule:
            return self.fill_schedule.pop(0)
        return float(order.remaining_quantity or 0.0)


def _bar(price: float) -> pd.Series:
    return pd.Series({"open": price, "close": price, "volume": 1_000.0})


@pytest.mark.parametrize(
    ("direction", "prices", "exit_decision", "exit_fill"),
    [
        (1, [10.0, 11.0, 12.0], 13.0, 12.9),
        (-1, [10.0, 9.0, 8.0], 7.0, 7.1),
    ],
    ids=["long", "short"],
)
def test_partial_entry_fills_aggregate_basis_and_costs(
    direction: int,
    prices: list[float],
    exit_decision: float,
    exit_fill: float,
) -> None:
    engine = PartialFillEngine(
        {"initial_cash": 10_000.0},
        fill_schedule=[2.0, 2.0, 1.0],
    )
    dates = pd.date_range("2025-01-01", periods=4, freq="D")
    order = engine._create_order(
        symbol="X",
        event_type="entry",
        direction=direction,
        quantity=5.0,
        timestamp=dates[0],
        decision_price=prices[0],
        reason="signal",
        signal_time=dates[0] - pd.Timedelta(days=1),
    )

    for timestamp, price in zip(dates[:3], prices):
        engine._process_order(order, _bar(price), timestamp)

    assert order.status == "filled"
    assert order.filled_quantity == pytest.approx(5.0)
    assert [fill.quantity for fill in engine.fills] == pytest.approx([2.0, 2.0, 1.0])
    assert {fill.order_id for fill in engine.fills} == {order.order_id}
    assert [fill.remaining_quantity for fill in engine.fills] == pytest.approx([3.0, 1.0, 0.0])
    position = engine.positions["X"]
    expected_fill_basis = sum(
        quantity * (price + 0.1 * direction)
        for quantity, price in zip([2.0, 2.0, 1.0], prices)
    ) / 5.0
    expected_decision_basis = sum(
        quantity * price
        for quantity, price in zip([2.0, 2.0, 1.0], prices)
    ) / 5.0
    assert position.size == pytest.approx(5.0)
    assert position.entry_price == pytest.approx(expected_fill_basis)
    assert position.entry_decision_price == pytest.approx(expected_decision_basis)

    engine._bar_idx = 3
    engine._close_position(
        "X",
        exit_fill,
        dates[3],
        "signal",
        exit_decision_price=exit_decision,
    )
    assert not engine.positions
    assert len(engine.trades) == 1
    trade = engine.trades[0]
    assert trade.size == pytest.approx(5.0)
    assert trade.commission == pytest.approx(sum(fill.commission for fill in engine.fills))
    assert trade.slippage_cost == pytest.approx(
        sum(fill.slippage_cost for fill in engine.fills)
    )
    assert trade.net_pnl == pytest.approx(
        trade.gross_pnl - trade.commission - trade.slippage_cost
    )
    assert engine.capital == pytest.approx(engine.initial_capital + trade.net_pnl)


def test_partial_exit_then_terminal_close_reconciles_residual_once() -> None:
    engine = PartialFillEngine(
        {"initial_cash": 10_000.0},
        fill_schedule=[5.0, 2.0],
    )
    dates = pd.date_range("2025-02-01", periods=3, freq="D")
    entry = engine._create_order(
        symbol="X",
        event_type="entry",
        direction=1,
        quantity=5.0,
        timestamp=dates[0],
        decision_price=10.0,
        reason="signal",
    )
    engine._process_order(entry, _bar(10.0), dates[0])

    exit_order = engine._create_order(
        symbol="X",
        event_type="exit",
        direction=1,
        quantity=5.0,
        timestamp=dates[1],
        decision_price=12.0,
        reason="signal",
    )
    engine._bar_idx = 1
    engine._process_order(exit_order, _bar(12.0), dates[1])
    assert exit_order.status == "partially_filled"
    assert engine.positions["X"].size == pytest.approx(3.0)

    engine._bar_idx = 2
    engine._close_position(
        "X", 12.9, dates[2], "end_of_backtest", exit_decision_price=13.0,
    )

    assert exit_order.status == "cancelled"
    assert exit_order.filled_quantity == pytest.approx(2.0)
    assert exit_order.cancelled_quantity == pytest.approx(3.0)
    assert not engine.positions
    assert len(engine.trades) == 1
    assert len(engine.fills) == 3
    assert engine.trades[0].size == pytest.approx(5.0)
    assert engine.trades[0].exit_reason == "end_of_backtest"
    assert engine.trades[0].commission == pytest.approx(
        sum(fill.commission for fill in engine.fills)
    )
    assert engine.trades[0].slippage_cost == pytest.approx(
        sum(fill.slippage_cost for fill in engine.fills)
    )
    assert engine.capital == pytest.approx(
        engine.initial_capital + engine.trades[0].net_pnl
    )


def test_multiple_assets_can_hold_independent_partial_orders() -> None:
    engine = PartialFillEngine(
        {"initial_cash": 10_000.0},
        fill_schedule=[1.0, 1.5],
    )
    timestamp = pd.Timestamp("2025-03-01")
    orders = []
    for symbol, quantity, price in [("A", 3.0, 10.0), ("B", 4.0, 20.0)]:
        order = engine._create_order(
            symbol=symbol,
            event_type="entry",
            direction=1,
            quantity=quantity,
            timestamp=timestamp,
            decision_price=price,
            reason="signal",
        )
        engine._process_order(order, _bar(price), timestamp)
        orders.append(order)

    assert all(order.status == "partially_filled" for order in orders)
    assert engine.positions["A"].size == pytest.approx(1.0)
    assert engine.positions["B"].size == pytest.approx(1.5)
    assert set(engine.pending_orders) == {"A", "B"}
    assert len({fill.order_id for fill in engine.fills}) == 2


def test_zero_fill_order_can_be_cancelled_without_costs() -> None:
    engine = PartialFillEngine(
        {"initial_cash": 10_000.0},
        fill_schedule=[0.0],
    )
    timestamp = pd.Timestamp("2025-04-01")
    order = engine._create_order(
        symbol="X",
        event_type="entry",
        direction=1,
        quantity=4.0,
        timestamp=timestamp,
        decision_price=10.0,
        reason="signal",
    )
    assert engine._process_order(order, _bar(10.0), timestamp) == 0.0
    order.cancel(timestamp + pd.Timedelta(days=1))

    assert order.status == "cancelled"
    assert order.cancelled_quantity == pytest.approx(4.0)
    assert not engine.fills
    assert not engine.positions
    assert engine.capital == pytest.approx(engine.initial_capital)

    metrics = calc_execution_metrics(
        pd.DataFrame(),
        engine.fills,
        observation_count=0,
        orders=engine.orders,
    )
    assert metrics["fill_ratio"] == pytest.approx(0.0)
    assert metrics["total_cancelled_quantity"] == pytest.approx(4.0)
    assert metrics["total_unfilled_quantity"] == pytest.approx(4.0)
    assert metrics["cancelled_order_count"] == pytest.approx(1.0)
    assert math.isfinite(metrics["fill_ratio"])


def test_execution_metrics_count_multi_fill_orders() -> None:
    engine = PartialFillEngine(
        {"initial_cash": 10_000.0},
        fill_schedule=[2.0, 3.0],
    )
    dates = pd.date_range("2025-05-01", periods=2, freq="D")
    order = engine._create_order(
        symbol="X",
        event_type="entry",
        direction=1,
        quantity=5.0,
        timestamp=dates[0],
        decision_price=10.0,
        reason="signal",
    )
    engine._process_order(order, _bar(10.0), dates[0])
    engine._process_order(order, _bar(10.0), dates[1])

    metrics = calc_execution_metrics(
        pd.DataFrame(),
        engine.fills,
        observation_count=2,
        orders=engine.orders,
    )
    assert metrics["order_count"] == pytest.approx(1.0)
    assert metrics["filled_order_count"] == pytest.approx(1.0)
    assert metrics["partial_fill_order_count"] == pytest.approx(1.0)
    assert metrics["total_requested_quantity"] == pytest.approx(5.0)
    assert metrics["total_filled_quantity"] == pytest.approx(5.0)
    assert metrics["fill_ratio"] == pytest.approx(1.0)

    commission_by_day = pd.Series(0.0, index=dates)
    slippage_by_day = pd.Series(0.0, index=dates)
    for fill in engine.fills:
        commission_by_day.loc[fill.timestamp] += fill.commission
        slippage_by_day.loc[fill.timestamp] += fill.slippage_cost
    daily_cost = commission_by_day + slippage_by_day
    daily = pd.DataFrame({
        "net_return": [0.0, 0.0],
        "gross_return": daily_cost / engine.initial_capital,
        "daily_commission": commission_by_day,
        "daily_slippage_cost": slippage_by_day,
        "daily_total_cost": daily_cost,
        "one_way_turnover": [0.1, 0.1],
        "gross_exposure": [0.1, 0.1],
        "net_exposure": [0.1, 0.1],
        "equity": [engine.initial_capital, engine.initial_capital],
        "gross_equity": [
            engine.initial_capital,
            engine.initial_capital + float(daily_cost.sum()),
        ],
    }, index=dates)
    outputs = build_reporting_outputs(
        daily_accounting=daily,
        executed_positions=pd.DataFrame({"X": [0.1, 0.1]}, index=dates),
        trades=[],
        fills=engine.fills,
        orders=engine.orders,
        scalar_metrics={},
        starting_capital=engine.initial_capital,
        bars_per_year=252,
        final_capital=engine.capital,
        open_position_count=1,
    )
    summary = outputs["performance_summary"]
    assert summary["fill_ratio"] == pytest.approx(1.0)
    assert summary["partial_fill_order_count"] == 1
    assert summary["total_requested_quantity"] == pytest.approx(5.0)
    assert "Order fill ratio: 100.00%" in outputs["performance_report"]
