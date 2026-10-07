"""India circuit checks use the fill side, including shared composite positions."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engines.composite import CompositeEngine
from backtest.engines.india_equity import IndiaEquityEngine
from backtest.models import Position


SYMBOL = "RELIANCE.NS"
ENTRY_DATE = pd.Timestamp("2024-04-01")
NEXT_DATE = pd.Timestamp("2024-04-02")


@pytest.fixture(params=["single", "composite"])
def engine(request):
    config = {"initial_cash": 1_000_000, "allow_short": True, "slippage": 0.001}
    if request.param == "composite":
        result = CompositeEngine(config, [SYMBOL, "TCS.NS"])
        assert not result._rule_engines["india_equity"].positions
    else:
        result = IndiaEquityEngine(config)
    result._active_symbol = SYMBOL
    # Exercise the previous-close panel used by real runs: no pre_close field.
    result._close_arr = np.array([[100.0]])
    result._code_to_col = {SYMBOL: 0}
    result._bar_idx = 1
    return result


def _hold(engine, direction):
    engine.positions[SYMBOL] = Position(
        symbol=SYMBOL, direction=direction, size=10, entry_price=100.0,
        entry_time=ENTRY_DATE,
    )


@pytest.mark.parametrize(
    ("direction", "position_direction", "buying"),
    [(1, None, True), (-1, None, False), (0, 1, False), (0, -1, True)],
    ids=["open-long", "open-short", "close-long", "cover-short"],
)
@pytest.mark.parametrize(
    ("open_price", "buy_allowed", "sell_allowed"),
    [
        (119.9, False, True),  # Buy slippage crosses 120; raw open is inside.
        (119.8, True, True),
        (80.05, True, False),  # Sell slippage crosses 80; raw open is inside.
        (80.2, True, True),
    ],
)
def test_fill_side_controls_the_band(
    engine, direction, position_direction, buying, open_price, buy_allowed, sell_allowed,
):
    if position_direction is not None:
        _hold(engine, position_direction)
    # The later close must not rescue or veto an execution at the open.
    bar = pd.Series({"open": open_price, "close": 100.0}, name=NEXT_DATE)
    expected = buy_allowed if buying else sell_allowed
    assert engine.can_execute(SYMBOL, direction, bar) is expected


@pytest.mark.parametrize("position_direction", [1, -1], ids=["long", "short"])
@pytest.mark.parametrize("date_field", [None, "date", "trade_date"])
def test_existing_same_day_close_guard_is_preserved(engine, position_direction, date_field):
    """The delivery engine blocks same-day closes even with allow_short enabled."""
    _hold(engine, position_direction)
    bar = pd.Series({"open": 100.0, "close": 100.0}, name=ENTRY_DATE)
    if date_field is not None:
        bar.name = None
        bar[date_field] = ENTRY_DATE.isoformat()
    assert engine.can_execute(SYMBOL, 0, bar) is False


def test_blocked_short_cover_retains_position_until_a_fillable_bar(engine):
    """Run the actual open/close path so a rejected cover cannot book a trade."""
    dates = pd.bdate_range(ENTRY_DATE, periods=3)
    bars = pd.DataFrame(
        {"open": [100.0, 119.9, 110.0], "close": [100.0, 105.0, 110.0],
         "pre_close": [100.0, 100.0, 105.0]},
        index=dates,
    )
    engine._rebalance(SYMBOL, -0.1, bars, dates[0], 1_000_000)
    position = engine.positions[SYMBOL]
    assert position.direction == -1
    assert position.entry_price == pytest.approx(99.9)
    capital_before_cover = engine.capital

    engine._rebalance(SYMBOL, 0, bars, dates[1], 1_000_000)
    assert engine.positions[SYMBOL] is position
    assert engine.capital == capital_before_cover
    assert not engine.trades
    assert len(engine.fill_records) == 1

    engine._rebalance(SYMBOL, 0, bars, dates[2], 1_000_000)
    assert SYMBOL not in engine.positions
    assert len(engine.trades) == 1
    assert engine.trades[0].exit_time == dates[2]
    assert engine.trades[0].exit_price == pytest.approx(110.11)
    assert len(engine.fill_records) == 2
    if isinstance(engine, CompositeEngine):
        assert not engine._rule_engines["india_equity"].positions
