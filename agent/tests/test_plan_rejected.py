"""Tests for the BaseEngine._on_plan_rejected observation hook.

``_plan_open_order`` returns ``None`` for seven distinct reasons; these tests
pin each cause to its exact machine-readable reason string and prove the hook
is purely observational (no behavior change).
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engines.base import BaseEngine
from backtest.models import Position

_TS = pd.Timestamp("2026-01-02")
_REASONS = (
    "no_target_weight",
    "already_held",
    "no_data",
    "no_bar",
    "execution_blocked",
    "invalid_price",
    "zero_size",
)


class _RecorderEngine(BaseEngine):
    """Minimal engine whose _on_plan_rejected records (symbol, reason, ts)."""

    def __init__(self, **overrides):
        config = {"initial_cash": 1_000.0, "leverage": 1.0, "position_adjustment": "rebalance"}
        config.update(overrides)
        super().__init__(config)
        self.rejections: list[tuple[str, str, pd.Timestamp]] = []
        self.execute_ok = True

    def can_execute(self, symbol, direction, bar):
        return self.execute_ok

    def round_size(self, raw_size, price):
        return round(max(raw_size, 0.0), 6)

    def calc_commission(self, size, price, direction, is_open):
        return size * price * 0.0

    def apply_slippage(self, price, direction):
        return price

    def _on_plan_rejected(self, symbol, reason, timestamp):
        self.rejections.append((symbol, reason, timestamp))


class _ZeroLotEngine(_RecorderEngine):
    """Lot rounding that always truncates to zero (silent zero-fill)."""

    def round_size(self, raw_size, price):
        return 0.0


class _FuturesLotEngine(_RecorderEngine):
    """Futures-style whole-contract rounding: max(int(raw_size), 0)."""

    def round_size(self, raw_size, price):
        return float(max(int(raw_size), 0))


class _NoopHookEngine(_RecorderEngine):
    def _on_plan_rejected(self, symbol, reason, timestamp):
        pass


def _frame(open_price=100.0, ts=_TS):
    return pd.DataFrame({"open": [open_price], "close": [100.0]}, index=[ts])


def _force(engine, reason):
    """Call _plan_open_order in a way that triggers exactly `reason`."""
    if reason == "no_target_weight":
        return engine._plan_open_order("A", 0.0, _frame(), _TS, 1_000.0)
    if reason == "already_held":
        engine.positions["A"] = Position("A", 1, 100.0, _TS, 5.0)
        return engine._plan_open_order("A", 0.5, _frame(), _TS, 1_000.0)
    if reason == "no_data":
        return engine._plan_open_order("A", 0.5, None, _TS, 1_000.0)
    if reason == "no_bar":
        other_ts = pd.Timestamp("2026-01-03")
        return engine._plan_open_order("A", 0.5, _frame(), other_ts, 1_000.0)
    if reason == "execution_blocked":
        engine.execute_ok = False
        return engine._plan_open_order("A", 0.5, _frame(), _TS, 1_000.0)
    if reason == "invalid_price":
        return engine._plan_open_order("A", 0.5, _frame(open_price=0.0), _TS, 1_000.0)
    if reason == "zero_size":
        return engine._plan_open_order("A", 0.5, _frame(), _TS, 1_000.0)
    raise AssertionError(f"unknown reason {reason}")


@pytest.mark.parametrize("reason", _REASONS)
def test_each_cause_records_exact_reason(reason):
    engine = _ZeroLotEngine() if reason == "zero_size" else _RecorderEngine()
    ts = pd.Timestamp("2026-01-03") if reason == "no_bar" else _TS

    order = _force(engine, reason)

    assert order is None
    assert engine.rejections == [("A", reason, ts)]


def test_all_seven_reasons_are_pairwise_distinct():
    seen = []
    for reason in _REASONS:
        engine = _ZeroLotEngine() if reason == "zero_size" else _RecorderEngine()
        _force(engine, reason)
        seen.append(engine.rejections[0][1])

    assert len(seen) == len(_REASONS)
    assert len(set(seen)) == len(_REASONS)
    assert set(seen) == set(_REASONS)


def test_hook_not_called_when_order_is_planned():
    engine = _RecorderEngine()

    order = engine._plan_open_order("A", 0.5, _frame(), _TS, 1_000.0)

    assert order is not None
    assert order.size == 5.0
    assert engine.rejections == []


class _DefaultEngine(BaseEngine):
    """Engine with NO _on_plan_rejected override: inherits the BaseEngine no-op."""

    def __init__(self):
        super().__init__({"initial_cash": 1_000.0, "leverage": 1.0, "position_adjustment": "rebalance"})

    def can_execute(self, symbol, direction, bar):
        return True

    def round_size(self, raw_size, price):
        return round(max(raw_size, 0.0), 6)

    def calc_commission(self, size, price, direction, is_open):
        return size * price * 0.0

    def apply_slippage(self, price, direction):
        return price


def test_default_engine_has_zero_side_effects_for_every_cause():
    engine = _DefaultEngine()
    capital_before = engine.capital
    for reason in _REASONS:
        assert _force(engine, reason) is None

    assert engine.capital == capital_before
    assert engine.trades == []
    assert engine.fill_records == []


def test_futures_whole_contract_truncation_surfaces_zero_size():
    engine = _FuturesLotEngine()

    order = engine._plan_open_order("A", 0.0005, _frame(), _TS, 1_000.0)

    assert order is None
    assert engine.rejections == [("A", "zero_size", _TS)]
    assert engine.positions == {}


def test_recording_hook_does_not_change_execution_state():
    scenario_fill_and_reject = _run_fill_and_reject_scenario
    recorder = _RecorderEngine()
    noop = _NoopHookEngine()
    scenario_fill_and_reject(recorder)
    scenario_fill_and_reject(noop)

    assert recorder.rejections, "scenario must produce at least one rejection"
    assert noop.rejections == []
    assert recorder.capital == noop.capital
    assert recorder.positions == noop.positions
    assert recorder.trades == noop.trades
    assert recorder.fill_records == noop.fill_records


def _run_fill_and_reject_scenario(engine):
    """Weights that fill on bar 2 (bar 1 is weight 0), plus direct rejections."""
    dates = pd.date_range("2026-01-02", periods=2)
    data_map = {"A": pd.DataFrame({"open": [100.0, 100.0], "close": [100.0, 100.0]}, index=dates)}
    engine._execute_bars(
        dates,
        data_map,
        pd.DataFrame({"A": [100.0, 100.0]}, index=dates),
        pd.DataFrame({"A": [0.0, 0.5]}, index=dates),
        ["A"],
    )
    frame = _frame()
    # already_held: A was filled on bar 2 and allow_existing defaults to False.
    engine._plan_open_order("A", 0.5, frame, _TS, 1_000.0)
    # no_data and no_bar via direct calls.
    engine._plan_open_order("B", 0.5, None, _TS, 1_000.0)
    engine._plan_open_order("B", 0.5, frame, pd.Timestamp("2026-01-03"), 1_000.0)


# ---------------------------------------------------------------------------
# Default surfacing: a rejection nobody subclassed for still reaches the run
# ---------------------------------------------------------------------------


class _PlainEngine(BaseEngine):
    """No _on_plan_rejected override, and a lot rule that truncates to zero."""

    def __init__(self, *, truncate: bool = False):
        super().__init__(
            {"initial_cash": 1_000.0, "leverage": 1.0, "position_adjustment": "rebalance"}
        )
        self.execute_ok = True
        self._truncate = truncate

    def can_execute(self, symbol, direction, bar):
        return self.execute_ok

    def round_size(self, raw_size, price):
        return 0.0 if self._truncate else round(max(raw_size, 0.0), 6)

    def calc_commission(self, size, price, direction, is_open):
        return 0.0

    def apply_slippage(self, price, direction):
        return price


def test_wanted_but_unfillable_plans_are_counted_by_default():
    """A plain engine records the causes without any subclass override."""
    engine = _PlainEngine(truncate=True)
    assert engine._plan_open_order("A", 0.5, None, _TS, 1_000.0) is None  # no_data
    assert (
        engine._plan_open_order("A", 0.5, _frame(), pd.Timestamp("2026-01-03"), 1_000.0)
        is None
    )  # no_bar
    assert (
        engine._plan_open_order("A", 0.5, _frame(open_price=0.0), _TS, 1_000.0) is None
    )  # invalid_price
    assert engine._plan_open_order("A", 0.5, _frame(), _TS, 1_000.0) is None  # zero_size
    engine.execute_ok = False
    assert (
        engine._plan_open_order("A", 0.5, _frame(), _TS, 1_000.0) is None
    )  # execution_blocked
    # Benign causes must not be counted as findings.
    assert engine._plan_open_order("A", 0.0, _frame(), _TS, 1_000.0) is None

    metrics = engine._plan_rejection_metrics()
    assert metrics["unfilled_plan_rejections"] == 5
    assert metrics["unfilled_plan_rejections_by_symbol"] == {
        "A": {
            "no_data": 1,
            "no_bar": 1,
            "invalid_price": 1,
            "zero_size": 1,
            "execution_blocked": 1,
        }
    }
    assert set(metrics["unfilled_plan_rejections_by_symbol"]["A"]) == set(
        BaseEngine.UNFILLED_PLAN_REASONS
    )


def test_a_clean_run_reports_zero_unfilled_plans():
    engine = _PlainEngine()
    assert engine._plan_open_order("A", 0.5, _frame(), _TS, 1_000.0) is not None
    metrics = engine._plan_rejection_metrics()
    assert metrics["unfilled_plan_rejections"] == 0
    assert metrics["unfilled_plan_rejections_by_symbol"] == {}


def test_lot_truncated_sleeve_is_named_in_the_metrics():
    """#1235's motivating case: the sleeve that never fills must be nameable."""
    engine = _PlainEngine(truncate=True)
    for _ in range(3):
        engine._plan_open_order("ES", 0.0005, _frame(), _TS, 1_000.0)

    metrics = engine._plan_rejection_metrics()
    assert metrics["unfilled_plan_rejections"] == 3
    assert metrics["unfilled_plan_rejections_by_symbol"] == {"ES": {"zero_size": 3}}


def test_an_overriding_subclass_still_gets_the_default_counting():
    """A subclass that calls super() keeps both the hook and the metrics."""

    class _Both(_PlainEngine):
        def __init__(self):
            super().__init__(truncate=True)
            self.seen = []

        def _on_plan_rejected(self, symbol, reason, timestamp):
            self.seen.append((symbol, reason))
            super()._on_plan_rejected(symbol, reason, timestamp)

    engine = _Both()
    engine._plan_open_order("A", 0.5, _frame(), _TS, 1_000.0)
    assert engine.seen == [("A", "zero_size")]
    assert engine._plan_rejection_metrics()["unfilled_plan_rejections"] == 1
