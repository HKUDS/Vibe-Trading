"""#1470: the hold-mode capital scale-down search must not multiply rejections.

``position_adjustment="hold"`` (the default) bids every opening target at full
scale, and when the basket does not fit it bisects one common scale factor,
re-planning every leg on each of up to 50 probes. Every probe that rounds a
scaled leg to zero called ``_on_plan_rejected`` again, so a single cash-starved
open was reported as ~26 ``zero_size`` rejections — the very count #1235 added
to make a silently dropped sleeve visible, inflated ~25x and filed under the
lot-rounding reason, which calls for a different fix than "there was no cash".

The rebalance path already reports this shape once per bar (#1274): plan at
full scale, run the search without the hook, then record the legs that were
planned but not finally taken. These tests pin the same contract for hold mode.
"""

from __future__ import annotations

import collections

import pandas as pd
import pytest

from backtest.engines.global_futures import GlobalFuturesEngine

GC, SI, ES = "GC.COMEX", "SI.COMEX", "ES.COMEX"
_DATES = pd.DatetimeIndex(["2024-01-02", "2024-01-03"])
_PRICES = {GC: 1850.0, SI: 23.0, ES: 5000.0}


class _ProbeEngine(GlobalFuturesEngine):
    """Counts every hook call and records the orders that actually executed."""

    def __init__(self, config, blocked: tuple[str, ...] = ()):
        super().__init__(config)
        self.blocked = blocked
        self.calls: collections.Counter = collections.Counter()
        self.orders: list[tuple] = []

    def can_execute(self, symbol, direction, bar):
        if symbol in self.blocked:
            return False
        return super().can_execute(symbol, direction, bar)

    def _on_plan_rejected(self, symbol, reason, timestamp):
        self.calls[(symbol, reason)] += 1
        super()._on_plan_rejected(symbol, reason, timestamp)

    def _execute_open_order(self, order, ts):
        self.orders.append(
            (order.symbol, order.direction, round(order.size, 6), round(order.price, 4))
        )
        return super()._execute_open_order(order, ts)


def _bars(price: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": 1e5,
        },
        index=_DATES,
    )


def _run(
    targets: dict[str, list[float]],
    *,
    price_codes: tuple[str, ...],
    blocked: tuple[str, ...] = (),
    cash: float = 1_000_000.0,
) -> _ProbeEngine:
    engine = _ProbeEngine({"initial_cash": cash, "leverage": 1.0}, blocked=blocked)
    data_map = {c: _bars(_PRICES[c]) for c in price_codes}
    close = pd.DataFrame({c: data_map[c]["close"] for c in data_map})
    engine._execute_bars(
        _DATES,
        data_map,
        close,
        pd.DataFrame(targets, index=_DATES),
        list(targets),
    )
    return engine


def test_a_cash_starved_open_is_recorded_once_not_once_per_probe():
    """The issue's case B: SI takes 95% of the cash, GC's 30.5% cannot follow."""
    engine = _run({GC: [0.0, 0.305], SI: [0.95, 0.95]}, price_codes=(GC, SI))

    assert dict(engine.calls) == {(GC, "insufficient_capital"): 1}
    assert engine._plan_rejection_metrics() == {
        "unfilled_plan_rejections": 1,
        "unfilled_plan_rejections_by_symbol": {GC: {"insufficient_capital": 1}},
    }


def test_a_blocked_leg_is_recorded_once_even_while_the_basket_is_scaled():
    """Scaling cannot change a market rule, so probes must stay silent too.

    GC is blocked outright and ES is the leg that does not fit: neither cause
    is the search's to re-attribute, and on the buggy code GC alone was counted
    51 times (one full-scale bid plus 50 probes) and ES 21 times.
    """
    engine = _run(
        {SI: [0.95, 0.95], GC: [0.0, 0.305], ES: [0.0, 0.50]},
        price_codes=(GC, SI, ES),
        blocked=(GC,),
    )

    assert dict(engine.calls) == {
        (GC, "execution_blocked"): 1,
        (ES, "insufficient_capital"): 1,
    }
    assert engine._plan_rejection_metrics()["unfilled_plan_rejections"] == 2


def test_true_lot_rounding_is_still_reported_as_zero_size():
    """A target that never clears one lot is not a cash finding, and stays 1.

    No scaling search runs here (the basket is already empty), so this pins
    that the relabelling is confined to legs the search rounds away.
    """
    engine = _run({GC: [0.0, 0.0005]}, price_codes=(GC,))

    assert dict(engine.calls) == {(GC, "zero_size"): 1}
    assert engine._plan_rejection_metrics() == {
        "unfilled_plan_rejections": 1,
        "unfilled_plan_rejections_by_symbol": {GC: {"zero_size": 1}},
    }


def test_a_leg_that_survives_the_scale_search_is_not_a_rejection():
    """Scaling a basket down is only a finding for the legs it drops.

    GC fits on its own at a smaller size, so nothing was unfillable and the
    hook must stay silent — a count of 1 here would read as a sleeve that
    never entered the book.
    """
    engine = _run({GC: [0.9, 0.9]}, price_codes=(GC,))

    assert engine.calls == {}
    assert engine.orders == [(GC, 1, 4.0, 1850.555)]


def test_the_scale_search_still_fills_exactly_what_it_filled_before():
    """The fix is diagnostics only: same fills, same cash.

    Both values were measured on the buggy engine (26 rejections) and must not
    move — a counting fix that reshapes the basket would be a worse bug.
    """
    engine = _run({GC: [0.0, 0.305], SI: [0.95, 0.95]}, price_codes=(GC, SI))

    assert engine.orders == [(SI, 1, 8.0, 23.0069)]
    assert engine.capital == pytest.approx(999412.0)
