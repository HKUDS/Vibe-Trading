"""Payoff explorer math, checked against hand-computed strategies."""

from __future__ import annotations

import numpy as np
import pytest

from backtest.engines.options_portfolio import bs_price
from backtest.options_payoff import (
    OptionLeg,
    bull_call_spread,
    default_spot_grid,
    expiry_payoff,
    iron_condor,
    long_straddle,
    scenario_grid,
)

RATE = 0.05
IV = 0.3
T = 0.5


def _grid(center: float = 100.0) -> np.ndarray:
    return default_spot_grid(center, 0.6)


def test_long_call_breakeven_and_payoff():
    leg = OptionLeg("call", 100.0, 1)
    report = expiry_payoff([leg], _grid(), entry_spot=100.0, time_to_expiry=T, rate=RATE, iv=IV)

    premium = bs_price(100.0, 100.0, T, RATE, IV, "call")
    assert report.net_premium == pytest.approx(premium, rel=1e-9)
    assert report.breakevens == pytest.approx([100.0 + premium], abs=1e-6)
    # deep ITM: payoff tracks intrinsic minus premium
    deep = report.spot_grid[-1]
    assert report.payoff[-1] == pytest.approx(deep - 100.0 - premium, rel=1e-9)
    # deep OTM: flat loss of the premium
    assert report.payoff[0] == pytest.approx(-premium, rel=1e-9)
    assert report.profit_unbounded is True
    assert report.loss_unbounded is False


def test_short_put_breakeven_and_floor():
    leg = OptionLeg("put", 100.0, -1)
    report = expiry_payoff([leg], _grid(), entry_spot=100.0, time_to_expiry=T, rate=RATE, iv=IV)

    premium = bs_price(100.0, 100.0, T, RATE, IV, "put")
    assert report.net_premium == pytest.approx(-premium, rel=1e-9)
    assert report.breakevens == pytest.approx([100.0 - premium], abs=1e-6)
    # worst case is spot at zero: assignment minus the credit
    assert report.max_loss == pytest.approx(premium - 100.0, rel=1e-6)
    assert report.max_profit == pytest.approx(premium, rel=1e-6)


def test_bull_call_spread_shape():
    legs = bull_call_spread(95.0, 105.0)
    report = expiry_payoff(legs, _grid(), entry_spot=100.0, time_to_expiry=T, rate=RATE, iv=IV)

    long_leg = bs_price(100.0, 95.0, T, RATE, IV, "call")
    short_leg = bs_price(100.0, 105.0, T, RATE, IV, "call")
    debit = long_leg - short_leg
    assert report.net_premium == pytest.approx(debit, rel=1e-9)
    assert report.max_profit == pytest.approx(10.0 - debit, abs=1e-6)
    assert report.max_loss == pytest.approx(-debit, abs=1e-6)
    assert report.breakevens == pytest.approx([95.0 + debit], abs=1e-6)


def test_straddle_two_breakevens():
    legs = long_straddle(100.0)
    report = expiry_payoff(legs, _grid(), entry_spot=100.0, time_to_expiry=T, rate=RATE, iv=IV)

    cost = bs_price(100.0, 100.0, T, RATE, IV, "call") + bs_price(100.0, 100.0, T, RATE, IV, "put")
    assert len(report.breakevens) == 2
    assert report.breakevens == pytest.approx([100.0 - cost, 100.0 + cost], abs=1e-6)


def test_iron_condor_max_profit_inside_body():
    legs = iron_condor(90.0, 95.0, 105.0, 110.0)
    report = expiry_payoff(legs, _grid(), entry_spot=100.0, time_to_expiry=T, rate=RATE, iv=IV)

    # between the bodies every leg expires worthless, the credit is kept
    body = (report.spot_grid >= 95.0) & (report.spot_grid <= 105.0)
    assert np.all(report.payoff[body] == pytest.approx(-report.net_premium, abs=1e-9))
    assert report.net_premium < 0  # iron condor opens for a credit
    assert report.max_profit == pytest.approx(-report.net_premium, abs=1e-6)


def test_naked_short_call_marks_unbounded_loss():
    legs = [OptionLeg("call", 100.0, -1)]
    report = expiry_payoff(legs, _grid(), entry_spot=100.0, time_to_expiry=T, rate=RATE, iv=IV)

    assert report.loss_unbounded is True
    assert report.max_loss == float("-inf")
    assert report.profit_unbounded is False


def test_scenario_grid_zero_at_entry_cell():
    legs = long_straddle(100.0)
    spots = np.array([95.0, 100.0, 105.0])
    ivs = np.array([0.2, 0.3, 0.4])
    grid = scenario_grid(legs, spots, ivs, entry_spot=100.0, time_to_expiry=T, rate=RATE, entry_iv=IV)

    entry_row = int(np.where(ivs == IV)[0][0])
    entry_col = int(np.where(spots == 100.0)[0][0])
    assert grid[entry_row, entry_col] == pytest.approx(0.0, abs=1e-9)
    # a straddle is long vega: higher IV lifts it, lower IV sinks it
    assert grid[2, entry_col] > grid[entry_row, entry_col]
    assert grid[0, entry_col] < grid[entry_row, entry_col]


def test_explicit_premium_wins_over_bs():
    legs = [OptionLeg("call", 100.0, 1, premium=2.5)]
    report = expiry_payoff(legs, _grid(), entry_spot=100.0, time_to_expiry=T, rate=RATE, iv=IV)

    assert report.net_premium == pytest.approx(2.5, rel=1e-9)
    assert report.breakevens == pytest.approx([102.5], abs=1e-6)


def test_rejects_bad_inputs():
    with pytest.raises(ValueError):
        expiry_payoff([], _grid(), entry_spot=100.0, time_to_expiry=T)
    with pytest.raises(ValueError):
        expiry_payoff([OptionLeg("strangle", 100.0, 1)], _grid(), entry_spot=100.0, time_to_expiry=T)
    with pytest.raises(ValueError):
        bull_call_spread(105.0, 95.0)
    with pytest.raises(ValueError):
        iron_condor(95.0, 90.0, 105.0, 110.0)
