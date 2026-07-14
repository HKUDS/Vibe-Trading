"""Adversarial tests for Phase 6 execution eligibility and order lifecycle."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backtest.engines.base import BaseEngine
from backtest.metrics import calc_execution_metrics
from backtest.models import FillRecord, OrderRecord


class ExecutionRealismEngine(BaseEngine):
    """Deterministic engine with optional per-attempt fill quantities."""

    def __init__(
        self,
        config: dict,
        fill_schedule: list[float] | None = None,
    ) -> None:
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
        return 0.0

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


class ExitRejectingEngine(ExecutionRealismEngine):
    """Reject exits only, so same-bar resubmission behavior is observable."""

    def order_rejection_reason(
        self,
        order: OrderRecord,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> str | None:
        return "exit_rejected" if order.event_type == "exit" else None


def _bar(
    open_price: float = 10.0,
    *,
    low: float | None = None,
    high: float | None = None,
    volume: float = 1_000.0,
) -> pd.Series:
    return pd.Series({
        "open": open_price,
        "high": high if high is not None else open_price,
        "low": low if low is not None else open_price,
        "close": open_price,
        "volume": volume,
    })


def _dates(engine: BaseEngine, periods: int = 5) -> pd.DatetimeIndex:
    dates = pd.date_range("2025-01-01", periods=periods, freq="D")
    engine._execution_dates = pd.DatetimeIndex(dates)
    return dates


def _entry_order(
    engine: BaseEngine,
    timestamp: pd.Timestamp,
    *,
    symbol: str = "X",
    direction: int = 1,
    quantity: float = 5.0,
    order_type: str | None = None,
    limit_price: float | None = None,
    time_in_force: str | None = None,
) -> OrderRecord:
    return engine._create_order(
        symbol=symbol,
        event_type="entry",
        direction=direction,
        quantity=quantity,
        timestamp=timestamp,
        decision_price=10.0,
        reason="signal",
        signal_time=timestamp - pd.Timedelta(days=1),
        order_type=order_type,
        limit_price=limit_price,
        time_in_force=time_in_force,
    )


def test_latency_defers_execution_until_eligible_bar() -> None:
    engine = ExecutionRealismEngine({
        "initial_cash": 10_000.0,
        "execution_latency_bars": 2,
    })
    dates = _dates(engine)
    order = _entry_order(engine, dates[0])

    for index in (0, 1):
        engine._bar_idx = index
        assert engine._process_order(order, _bar(), dates[index]) == 0.0

    assert order.status == "open"
    assert order.deferred_bars == 2
    assert order.attempt_count == 0
    assert order.eligible_bar_index == 2
    assert order.eligible_time == dates[2]

    engine._bar_idx = 2
    assert engine._process_order(order, _bar(), dates[2]) == pytest.approx(5.0)
    assert order.status == "filled"
    assert order.attempt_count == 1
    assert engine.fills[0].eligible_bar_index == 2
    assert engine.fills[0].execution_bar_index == 2
    assert engine.fills[0].eligible_time == dates[2]


def test_buy_limit_requires_touch_and_never_fills_above_limit() -> None:
    engine = ExecutionRealismEngine({"initial_cash": 10_000.0})
    dates = _dates(engine)
    order = _entry_order(
        engine,
        dates[0],
        order_type="limit",
        limit_price=9.5,
    )

    engine._bar_idx = 0
    assert engine._process_order(
        order, _bar(10.0, low=9.6, high=10.2), dates[0],
    ) == 0.0
    assert order.status == "open"
    assert order.unfilled_eligible_bars == 1

    engine._bar_idx = 1
    assert engine._process_order(
        order, _bar(9.25, low=9.0, high=9.8), dates[1],
    ) == pytest.approx(5.0)
    fill = engine.fills[0]
    assert fill.order_type == "limit"
    assert fill.fill_price == pytest.approx(9.35)
    assert fill.fill_price <= float(fill.limit_price) + 1e-12


def test_sell_limit_requires_touch_and_never_fills_below_limit() -> None:
    engine = ExecutionRealismEngine({"initial_cash": 10_000.0})
    dates = _dates(engine)
    order = _entry_order(
        engine,
        dates[0],
        direction=-1,
        order_type="limit",
        limit_price=10.5,
    )

    engine._bar_idx = 0
    assert engine._process_order(
        order, _bar(10.0, low=9.8, high=10.6), dates[0],
    ) == pytest.approx(5.0)
    fill = engine.fills[0]
    assert fill.side == "sell"
    assert fill.fill_price == pytest.approx(10.5)
    assert fill.fill_price >= float(fill.limit_price) - 1e-12


def test_expiry_is_inclusive_of_configured_last_eligible_bar() -> None:
    engine = ExecutionRealismEngine({
        "initial_cash": 10_000.0,
        "order_expiry_bars": 0,
    })
    dates = _dates(engine, 2)
    order = _entry_order(
        engine,
        dates[0],
        quantity=2.0,
        order_type="limit",
        limit_price=9.0,
    )

    engine._bar_idx = 0
    assert engine._process_order(
        order, _bar(10.0, low=9.5, high=10.5), dates[0],
    ) == 0.0
    assert order.status == "open"
    assert order.attempt_count == 1

    engine._bar_idx = 1
    assert engine._process_order(order, _bar(), dates[1]) == 0.0
    assert order.status == "expired"
    assert order.status_reason == "order_expiry_bars"
    assert order.cancelled_quantity == pytest.approx(2.0)
    assert order.filled_quantity + order.cancelled_quantity == pytest.approx(
        order.requested_quantity
    )


def test_ioc_partial_fill_cancels_residual_on_first_eligible_attempt() -> None:
    engine = ExecutionRealismEngine(
        {"initial_cash": 10_000.0},
        fill_schedule=[2.0],
    )
    dates = _dates(engine)
    order = _entry_order(engine, dates[0], time_in_force="IOC")

    engine._bar_idx = 0
    assert engine._process_order(order, _bar(), dates[0]) == pytest.approx(2.0)
    assert order.status == "cancelled"
    assert order.status_reason == "ioc_residual"
    assert order.filled_quantity == pytest.approx(2.0)
    assert order.cancelled_quantity == pytest.approx(3.0)
    assert order.remaining_quantity == pytest.approx(0.0)
    assert len(engine.fills) == 1
    assert engine.fills[0].time_in_force == "IOC"


def test_fok_rejects_partial_capacity_and_accepts_complete_fill() -> None:
    dates = pd.date_range("2025-01-01", periods=2, freq="D")

    blocked = ExecutionRealismEngine(
        {"initial_cash": 10_000.0},
        fill_schedule=[2.0],
    )
    blocked._execution_dates = dates
    blocked_order = _entry_order(
        blocked, dates[0], time_in_force="FOK",
    )
    blocked._bar_idx = 0
    assert blocked._process_order(blocked_order, _bar(), dates[0]) == 0.0
    assert blocked_order.status == "cancelled"
    assert blocked_order.status_reason == "fok_not_fully_fillable"
    assert blocked_order.filled_quantity == pytest.approx(0.0)
    assert not blocked.fills

    complete = ExecutionRealismEngine(
        {"initial_cash": 10_000.0},
        fill_schedule=[5.0],
    )
    complete._execution_dates = dates
    complete_order = _entry_order(
        complete, dates[0], time_in_force="FOK",
    )
    complete._bar_idx = 0
    assert complete._process_order(
        complete_order, _bar(), dates[0],
    ) == pytest.approx(5.0)
    assert complete_order.status == "filled"
    assert len(complete.fills) == 1


def test_venue_rejection_is_terminal_and_auditable() -> None:
    engine = ExecutionRealismEngine({
        "initial_cash": 10_000.0,
        "venue_reject_symbols": {"X": "symbol_halted"},
    })
    dates = _dates(engine)
    order = _entry_order(engine, dates[0], quantity=3.0)

    engine._bar_idx = 0
    assert engine._process_order(order, _bar(), dates[0]) == 0.0
    assert order.status == "rejected"
    assert order.status_reason == "symbol_halted"
    assert order.attempt_count == 1
    assert order.cancelled_quantity == pytest.approx(3.0)
    assert "X" not in engine.pending_orders
    assert not engine.fills


def test_max_unfilled_bars_cancels_persistent_gtc_limit() -> None:
    engine = ExecutionRealismEngine({
        "initial_cash": 10_000.0,
        "max_unfilled_bars": 2,
    })
    dates = _dates(engine)
    order = _entry_order(
        engine,
        dates[0],
        order_type="limit",
        limit_price=9.0,
    )

    for index in (0, 1):
        engine._bar_idx = index
        engine._process_order(
            order, _bar(10.0, low=9.5, high=10.5), dates[index],
        )

    assert order.status == "cancelled"
    assert order.unfilled_eligible_bars == 2
    assert order.status_reason == "max_unfilled_bars:limit_not_touched"


def test_nonfinite_fill_quantity_is_audited_as_zero_fill() -> None:
    engine = ExecutionRealismEngine(
        {"initial_cash": 10_000.0},
        fill_schedule=[float("nan")],
    )
    dates = _dates(engine)
    order = _entry_order(engine, dates[0], time_in_force="IOC")

    engine._bar_idx = 0
    assert engine._process_order(order, _bar(), dates[0]) == 0.0
    assert order.status == "cancelled"
    assert order.status_reason == "ioc_zero_fill_quantity"
    assert order.unfilled_eligible_bars == 1
    assert not engine.fills


def test_rejected_pending_exit_is_not_resubmitted_on_same_bar() -> None:
    engine = ExitRejectingEngine({"initial_cash": 10_000.0})
    dates = _dates(engine, 3)
    entry = _entry_order(engine, dates[0], quantity=2.0)
    engine._bar_idx = 0
    engine._process_order(entry, _bar(), dates[0])
    assert entry.status == "filled"

    engine._bar_idx = 1
    exit_order = engine._create_order(
        symbol="X",
        event_type="exit",
        direction=1,
        quantity=2.0,
        timestamp=dates[1],
        decision_price=10.0,
        reason="signal",
    )
    frame = pd.DataFrame(
        [dict(_bar()), dict(_bar()), dict(_bar())],
        index=dates,
    )
    engine._rebalance("X", 0.0, frame, dates[1], engine.capital)

    assert exit_order.status == "rejected"
    assert exit_order.status_reason == "exit_rejected"
    assert len(engine.orders) == 2
    assert engine.positions["X"].size == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("quantity", "order_type", "limit_price", "reason"),
    [
        (float("nan"), "market", None, "invalid_quantity"),
        (1.0, "limit", float("inf"), "invalid_limit_price"),
    ],
)
def test_invalid_orders_are_rejected_without_entering_pending_state(
    quantity: float,
    order_type: str,
    limit_price: float | None,
    reason: str,
) -> None:
    engine = ExecutionRealismEngine({"initial_cash": 10_000.0})
    dates = _dates(engine)
    order = _entry_order(
        engine,
        dates[0],
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
    )

    assert order.status == "rejected"
    assert order.status_reason == reason
    assert order.symbol not in engine.pending_orders
    assert not engine.fills


def test_execution_metrics_detect_ledger_and_eligibility_violations() -> None:
    dates = pd.date_range("2025-02-01", periods=3, freq="D")
    order = OrderRecord(
        order_id="order_1",
        symbol="X",
        side="buy",
        event_type="entry",
        direction=1,
        requested_quantity=2.0,
        created_time=dates[0],
        decision_price=10.0,
        reason="signal",
        order_type="limit",
        limit_price=10.0,
        created_bar_index=0,
        eligible_bar_index=2,
        eligible_time=dates[2],
    )
    order.record_fill(1.0, dates[2])
    order.remaining_quantity = 0.25  # deliberately corrupt lifecycle total

    primary = FillRecord(
        timestamp=dates[1],
        symbol="X",
        side="buy",
        event_type="entry",
        direction=1,
        quantity=0.5,
        decision_price=10.0,
        fill_price=11.0,
        notional=5.5,
        commission=0.0,
        slippage_cost=0.0,
        reason="signal",
        order_id="order_1",
        order_type="limit",
        limit_price=10.0,
        eligible_time=dates[2],
        eligible_bar_index=2,
        execution_bar_index=1,
    )
    orphan = FillRecord(
        dates[1], "X", "buy", "entry", 1, 0.25, 10.0, 10.0,
        2.5, 0.0, 0.0, "signal", order_id="missing_order",
    )
    unlinked = FillRecord(
        dates[1], "X", "buy", "entry", 1, 0.25, 10.0, 10.0,
        2.5, 0.0, 0.0, "signal",
    )

    metrics = calc_execution_metrics(
        pd.DataFrame(),
        [primary, orphan, unlinked],
        observation_count=3,
        orders=[order],
    )

    assert metrics["limit_price_violation_count"] == pytest.approx(1.0)
    assert metrics["execution_before_eligibility_count"] == pytest.approx(1.0)
    assert metrics["orphan_fill_count"] == pytest.approx(1.0)
    assert metrics["unlinked_fill_count"] == pytest.approx(1.0)
    assert metrics["fill_quantity_mismatch_count"] == pytest.approx(1.0)
    assert metrics["order_lifecycle_violation_count"] == pytest.approx(1.0)
    assert all(math.isfinite(float(value)) for value in metrics.values())


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"order_type": "stop"}, "order_type"),
        ({"time_in_force": "DAY"}, "time_in_force"),
        ({"execution_latency_bars": 1.5}, "execution_latency_bars"),
        ({"order_expiry_bars": -1}, "order_expiry_bars"),
        ({"max_unfilled_bars": True}, "max_unfilled_bars"),
    ],
)
def test_invalid_execution_config_is_rejected(
    config: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ExecutionRealismEngine({"initial_cash": 10_000.0, **config})
