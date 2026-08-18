"""A drift band decides when a resize is worth trading (#918 follow-on).

Without one, the only thing separating "resize" from "leave it alone" under
``position_adjustment="rebalance"`` was the slippage width: a 0.01% daily move
re-pinned the position on 19 of 30 bars. That is noise being traded, and it
overrode whatever rebalance cadence the strategy had written for itself.
"""

from __future__ import annotations

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


_BARS = 60


def _rising_series() -> tuple[pd.DatetimeIndex, pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2026-01-05", periods=_BARS)
    prices = [100.0 * (1.005**i) for i in range(_BARS)]
    bars = pd.DataFrame({"open": prices, "close": prices}, index=dates)
    return dates, bars, pd.DataFrame({"A": bars["close"]}, index=dates)


def _run(tolerance: float, targets: list[float], mode: str = "rebalance") -> _Engine:
    dates, bars, close_df = _rising_series()
    engine = _Engine(
        {
            "initial_cash": 10_000_000.0,
            "position_adjustment": mode,
            "rebalance_tolerance": tolerance,
        }
    )
    engine._execute_bars(
        dates, {"A": bars}, close_df, pd.DataFrame({"A": targets}, index=dates), ["A"]
    )
    return engine


def test_the_default_band_is_zero_and_changes_nothing() -> None:
    """Existing runs must not be rewritten by the introduction of the band."""
    engine = _Engine({"initial_cash": 10_000_000.0, "position_adjustment": "rebalance"})
    assert engine.rebalance_tolerance == 0.0

    fills = len(_run(0.0, [0.20] * _BARS).trades)
    assert fills == _BARS  # every bar, which is the behaviour being preserved


def test_a_band_stops_trading_the_drift_without_losing_the_target() -> None:
    """The point is fewer fills at a weight that is still on target."""
    counts = {tol: len(_run(tol, [0.20] * _BARS).trades) for tol in (0.0, 0.02, 0.05, 0.10)}

    assert counts[0.0] > counts[0.02] > counts[0.05] >= counts[0.10]
    assert counts[0.05] <= counts[0.0] / 5

    weights = [
        snapshot.get("A", 0.0)
        for _, snapshot in _run(0.05, [0.20] * _BARS).actual_position_snapshots
    ]
    # Fewer trades, and the position never wanders far from the 20% it targets.
    assert max(weights[:-1]) < 0.21


def test_a_real_target_change_executes_at_any_band() -> None:
    """A changed target moves the reference far past any sane tolerance."""
    targets = [0.20] * 30 + [0.60] * (_BARS - 30)

    for tolerance in (0.0, 0.05, 0.25):
        engine = _run(tolerance, targets)
        weights = [s.get("A", 0.0) for _, s in engine.actual_position_snapshots]
        assert weights[30] == pytest.approx(0.60, abs=0.01), tolerance


def test_the_band_does_not_apply_to_hold_mode() -> None:
    """Hold mode never resizes, so a band there would be a silent no-op."""
    engine = _run(0.05, [0.20] * _BARS, mode="hold")

    # Exactly one round trip: opened once, never resized on the way, closed by
    # the end of the backtest rather than by any rebalance decision.
    assert len(engine.trades) == 1
    assert engine.trades[0].exit_reason == "end_of_backtest"
    assert engine.rebalance_tolerance == 0.05


@pytest.mark.parametrize("value", [-0.01, float("nan"), float("inf")])
def test_an_unusable_band_is_refused(value: float) -> None:
    """A band is a modelling choice; a meaningless one must not be assumed away."""
    with pytest.raises(ValueError, match="rebalance_tolerance"):
        _Engine({"initial_cash": 1_000.0, "rebalance_tolerance": value})
