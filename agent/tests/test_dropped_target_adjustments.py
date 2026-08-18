"""Hold mode may drop a requested resize, but never silently (#918).

`position_adjustment="hold"` executes a target change only when the direction
flips or the target reaches zero, so a same-direction resize is dropped. That
is the mode's job — "enter once, hold to exit" — but the report used to show a
rebalance count taken from the *requested* targets with nothing saying which of
those requests reached the book.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from backtest.engines.base import BaseEngine


class _Engine(BaseEngine):
    def can_execute(self, symbol, direction, bar):
        return True

    def round_size(self, raw_size, price):
        return float(int(raw_size))

    def calc_commission(self, size, price, direction, is_open):
        return 0.0

    def apply_slippage(self, price, direction):
        return price * (1 + 0.0005 * direction)


def _flat_bars(periods: int) -> tuple[pd.DatetimeIndex, pd.DataFrame]:
    dates = pd.bdate_range("2026-01-05", periods=periods)
    bars = pd.DataFrame({"open": [100.0] * periods, "close": [100.0] * periods}, index=dates)
    return dates, bars


def test_a_dropped_resize_is_recorded_and_warned(caplog: pytest.LogCaptureFixture) -> None:
    """The strategy asked to move 0.20 -> 0.60 -> 0.30 and got none of it."""
    dates, bars = _flat_bars(4)
    close_df = pd.DataFrame({"A": bars["close"]}, index=dates)
    targets = pd.DataFrame({"A": [0.20, 0.60, 0.30, 0.30]}, index=dates)
    engine = _Engine({"initial_cash": 100_000.0})

    with caplog.at_level(logging.WARNING):
        engine._execute_bars(dates, {"A": bars}, close_df, targets, ["A"])

    events = engine.dropped_target_adjustments
    assert [event["symbol"] for event in events] == ["A", "A"]
    assert [event["requested_target_weight"] for event in events] == [0.60, 0.30]
    assert [event["previous_target_weight"] for event in events] == [0.20, 0.60]
    assert any("dropped a resize" in message for message in caplog.messages)


def test_price_drift_alone_is_not_a_dropped_request() -> None:
    """A buy-and-hold weight drifts by design; reporting it would be noise.

    This is why the check compares against the previous TARGET rather than the
    current weight: on a rising series the held weight leaves 0.20 on its own,
    and comparing against it would flag every bar of an untouched position.
    """
    periods = 40
    dates = pd.bdate_range("2026-01-05", periods=periods)
    prices = [100.0 * (1.01**i) for i in range(periods)]
    bars = pd.DataFrame({"open": prices, "close": prices}, index=dates)
    close_df = pd.DataFrame({"A": bars["close"]}, index=dates)
    targets = pd.DataFrame({"A": [0.20] * periods}, index=dates)
    engine = _Engine({"initial_cash": 1_000_000.0})

    engine._execute_bars(dates, {"A": bars}, close_df, targets, ["A"])

    weights = [snapshot.get("A", 0.0) for _, snapshot in engine.actual_position_snapshots]
    assert weights[-2] > weights[0]  # the position really did drift
    assert engine.dropped_target_adjustments == []


def test_rebalance_mode_drops_nothing() -> None:
    """Nothing is dropped when every target change is executed."""
    dates, bars = _flat_bars(4)
    close_df = pd.DataFrame({"A": bars["close"]}, index=dates)
    targets = pd.DataFrame({"A": [0.20, 0.60, 0.30, 0.30]}, index=dates)
    engine = _Engine({"initial_cash": 100_000.0, "position_adjustment": "rebalance"})

    engine._execute_bars(dates, {"A": bars}, close_df, targets, ["A"])

    assert engine.dropped_target_adjustments == []


def test_an_exit_or_a_reversal_is_executed_not_dropped() -> None:
    """Hold mode does honour a flip and a flat target, so neither is reported."""
    dates, bars = _flat_bars(4)
    close_df = pd.DataFrame({"A": bars["close"]}, index=dates)
    targets = pd.DataFrame({"A": [0.20, 0.0, -0.20, -0.20]}, index=dates)
    engine = _Engine({"initial_cash": 100_000.0})

    engine._execute_bars(dates, {"A": bars}, close_df, targets, ["A"])

    assert engine.dropped_target_adjustments == []
