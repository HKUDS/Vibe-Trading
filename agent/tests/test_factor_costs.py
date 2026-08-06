"""Tests for backtest.factor_costs.

The load-bearing test is the one showing a high-turnover factor is eroded and a
low-turnover one is not. A cost model that charges everyone equally, or charges
nobody, would pass a suite that only checked "cost >= 0".
"""

import numpy as np
import pandas as pd
import pytest

from backtest.factor_costs import (
    DEFAULT_MAX_PARTICIPATION,
    MARKET_BORROW_RATES,
    apply_adv_capacity,
    borrow_cost,
    rebalance_cost,
)


def _w(**kwargs):
    return pd.Series(kwargs, dtype=float)


# --- ADV capacity ---


def test_a_trade_within_capacity_fills_completely():
    target = _w(A=0.10, B=-0.10)
    current = _w(A=0.0, B=0.0)
    adv = _w(A=1e9, B=1e9)
    result = apply_adv_capacity(target, current, adv, capital=1e6)

    assert result.achieved_weights["A"] == pytest.approx(0.10)
    assert result.achieved_weights["B"] == pytest.approx(-0.10)
    assert result.unfilled_weights.abs().sum() == pytest.approx(0.0)
    assert result.capped_symbols == ()


def test_an_oversized_trade_moves_part_way_and_reports_the_shortfall():
    # ADV 1,000,000 at 10% participation = 100,000 tradeable; capital 1,000,000
    # so the largest weight change is 0.10. Asking for 0.30 gets 0.10.
    target = _w(A=0.30)
    current = _w(A=0.0)
    adv = _w(A=1_000_000.0)
    result = apply_adv_capacity(target, current, adv, capital=1_000_000.0)

    assert result.achieved_weights["A"] == pytest.approx(0.10)
    assert result.unfilled_weights["A"] == pytest.approx(0.20)
    assert result.capped_symbols == ("A",)
    assert result.participation["A"] == pytest.approx(DEFAULT_MAX_PARTICIPATION)


def test_the_shortfall_is_neither_silently_filled_nor_silently_dropped():
    target = _w(A=0.30)
    current = _w(A=0.0)
    adv = _w(A=1_000_000.0)
    result = apply_adv_capacity(target, current, adv, capital=1_000_000.0)

    # Not filled: achieved is short of target.
    assert result.achieved_weights["A"] < result.requested_weights["A"]
    # Not dropped: the difference is reported and reconciles exactly.
    assert (
        result.achieved_weights["A"] + result.unfilled_weights["A"]
        == pytest.approx(result.requested_weights["A"])
    )


def test_a_name_with_unknown_volume_is_untradeable_not_infinitely_liquid():
    target = _w(A=0.20, B=0.20)
    current = _w(A=0.0, B=0.0)
    adv = _w(A=1e12)  # B has no ADV at all
    result = apply_adv_capacity(target, current, adv, capital=1e6)

    assert result.achieved_weights["A"] == pytest.approx(0.20)
    assert result.achieved_weights["B"] == pytest.approx(0.0)
    assert result.unfilled_weights["B"] == pytest.approx(0.20)


def test_zero_and_negative_adv_are_treated_as_untradeable():
    for bad in (0.0, -5.0):
        result = apply_adv_capacity(_w(A=0.1), _w(A=0.0), _w(A=bad), capital=1e6)
        assert result.achieved_weights["A"] == pytest.approx(0.0)


def test_capacity_caps_exits_as_well_as_entries():
    # Getting out is a trade too, and an illiquid name traps you.
    target = _w(A=0.0)
    current = _w(A=0.30)
    adv = _w(A=1_000_000.0)
    result = apply_adv_capacity(target, current, adv, capital=1_000_000.0)

    assert result.achieved_weights["A"] == pytest.approx(0.20)
    assert result.capped_symbols == ("A",)


def test_names_only_in_one_vector_are_still_trades():
    result = apply_adv_capacity(
        _w(NEW=0.1), _w(OLD=0.1), _w(NEW=1e12, OLD=1e12), capital=1e6
    )
    assert result.achieved_weights["NEW"] == pytest.approx(0.1)
    assert result.achieved_weights["OLD"] == pytest.approx(0.0)


def test_higher_participation_allows_more_to_trade():
    args = (_w(A=0.30), _w(A=0.0), _w(A=1_000_000.0))
    tight = apply_adv_capacity(*args, capital=1_000_000.0, max_participation=0.05)
    loose = apply_adv_capacity(*args, capital=1_000_000.0, max_participation=0.20)
    assert loose.achieved_weights["A"] > tight.achieved_weights["A"]


@pytest.mark.parametrize("participation", [0.0, -0.1, 1.5])
def test_bad_participation_rejected(participation):
    with pytest.raises(ValueError, match="max_participation"):
        apply_adv_capacity(
            _w(A=0.1), _w(A=0.0), _w(A=1e9), capital=1e6, max_participation=participation
        )


def test_non_positive_capital_rejected():
    with pytest.raises(ValueError, match="capital"):
        apply_adv_capacity(_w(A=0.1), _w(A=0.0), _w(A=1e9), capital=0.0)


# --- borrow ---


def test_only_the_short_leg_is_charged():
    longs_only = borrow_cost(_w(A=0.5, B=0.5), periods_per_year=252, annual_rate=0.03)
    assert longs_only == 0.0

    with_short = borrow_cost(_w(A=0.5, B=-0.5), periods_per_year=252, annual_rate=0.03)
    assert with_short == pytest.approx(0.5 * 0.03 / 252)


def test_borrow_scales_with_short_exposure():
    small = borrow_cost(_w(A=-0.1), periods_per_year=252, annual_rate=0.05)
    large = borrow_cost(_w(A=-0.4), periods_per_year=252, annual_rate=0.05)
    assert large == pytest.approx(4 * small)


def test_periods_per_year_has_no_default_and_changes_the_charge():
    daily = borrow_cost(_w(A=-1.0), periods_per_year=252, annual_rate=0.05)
    monthly = borrow_cost(_w(A=-1.0), periods_per_year=12, annual_rate=0.05)
    assert monthly == pytest.approx(21 * daily)
    with pytest.raises(TypeError):
        borrow_cost(_w(A=-1.0), annual_rate=0.05)  # type: ignore[call-arg]


def test_per_symbol_rates_are_honoured():
    cost = borrow_cost(
        _w(EASY=-0.5, HARD=-0.5),
        periods_per_year=252,
        annual_rate=pd.Series({"EASY": 0.003, "HARD": 0.20}),
    )
    assert cost == pytest.approx((0.5 * 0.003 + 0.5 * 0.20) / 252)


def test_a_shorted_symbol_with_no_rate_is_an_error_not_a_free_borrow():
    with pytest.raises(ValueError, match="missing a rate"):
        borrow_cost(
            _w(A=-0.5, B=-0.5),
            periods_per_year=252,
            annual_rate=pd.Series({"A": 0.01}),
        )


def test_market_fallback_uses_the_indicative_table():
    cost = borrow_cost(_w(A=-1.0), periods_per_year=252, market="CN")
    assert cost == pytest.approx(MARKET_BORROW_RATES["CN"] / 252)


def test_a_shorting_book_with_no_rate_source_at_all_is_an_error():
    with pytest.raises(ValueError, match="supply annual_rate"):
        borrow_cost(_w(A=-0.5), periods_per_year=252)


def test_unknown_market_rejected():
    with pytest.raises(ValueError, match="unknown market"):
        borrow_cost(_w(A=-0.5), periods_per_year=252, market="MARS")


def test_negative_borrow_rate_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        borrow_cost(_w(A=-0.5), periods_per_year=252, annual_rate=-0.01)


# --- the whole point: turnover has to hurt ---


def test_a_high_turnover_factor_is_eroded_far_more_than_a_low_turnover_one():
    universe = [f"S{i:02d}" for i in range(20)]
    adv = pd.Series(1e12, index=universe)  # capacity is not the binding constraint
    flat = pd.Series(0.0, index=universe)

    # Low turnover: the book barely moves.
    low_target = flat.copy()
    low_target.iloc[:10] = 0.10
    low_cost, _ = rebalance_cost(
        low_target, low_target * 0.98, capital=1e8, periods_per_year=252,
        adv_value=adv, impact_model="fixed",
    )

    # High turnover: the book flips entirely.
    high_prev = flat.copy()
    high_prev.iloc[:10] = 0.10
    high_target = flat.copy()
    high_target.iloc[10:] = 0.10
    high_cost, _ = rebalance_cost(
        high_target, high_prev, capital=1e8, periods_per_year=252,
        adv_value=adv, impact_model="fixed",
    )

    assert high_cost.turnover > 20 * low_cost.turnover
    assert high_cost.total_cost > 20 * low_cost.total_cost


def test_cost_is_a_positive_drag_never_a_signed_adjustment():
    universe = ["A", "B"]
    result, _ = rebalance_cost(
        pd.Series([0.5, -0.5], index=universe),
        pd.Series([0.0, 0.0], index=universe),
        capital=1e8,
        periods_per_year=252,
        adv_value=pd.Series(1e12, index=universe),
        impact_model="fixed",
        borrow_annual_rate=0.03,
    )
    assert result.impact_cost > 0
    assert result.borrow_cost > 0
    assert result.total_cost == pytest.approx(result.impact_cost + result.borrow_cost)


def test_capacity_limits_show_up_as_unfilled_turnover():
    result, capacity = rebalance_cost(
        _w(A=0.50),
        _w(A=0.0),
        capital=1_000_000.0,
        periods_per_year=252,
        adv_value=_w(A=1_000_000.0),
        impact_model="fixed",
    )
    assert result.turnover == pytest.approx(0.10)
    assert result.unfilled_turnover == pytest.approx(0.40)
    assert result.capped_symbols == ("A",)
    assert capacity is not None


def test_no_adv_means_no_cap_and_that_is_an_assumption_of_infinite_liquidity():
    result, capacity = rebalance_cost(
        _w(A=0.50), _w(A=0.0), capital=1_000.0, periods_per_year=252,
        impact_model="fixed",
    )
    assert capacity is None
    assert result.unfilled_turnover == 0.0
    assert result.capped_symbols == ()


def test_sqrt_model_needs_a_volatility():
    with pytest.raises(ValueError, match="needs a volatility"):
        rebalance_cost(
            _w(A=0.1), _w(A=0.0), capital=1e6, periods_per_year=252,
            adv_value=_w(A=1e9), impact_model="sqrt",
        )


def test_sqrt_impact_grows_with_participation():
    args = dict(capital=1e8, periods_per_year=252, impact_model="sqrt", volatility=0.02)
    thin, _ = rebalance_cost(_w(A=0.05), _w(A=0.0), adv_value=_w(A=1e8), **args)
    thick, _ = rebalance_cost(_w(A=0.05), _w(A=0.0), adv_value=_w(A=1e12), **args)
    # The same trade against a thinner book is a larger share of volume, so it
    # costs more.
    assert thin.impact_cost > thick.impact_cost


def test_unknown_impact_model_rejected():
    with pytest.raises(ValueError, match="impact_model"):
        rebalance_cost(
            _w(A=0.1), _w(A=0.0), capital=1e6, periods_per_year=252,
            impact_model="magic",
        )


def test_zero_turnover_costs_nothing_but_borrow():
    held = _w(A=0.5, B=-0.5)
    result, _ = rebalance_cost(
        held, held, capital=1e8, periods_per_year=252,
        adv_value=_w(A=1e12, B=1e12), impact_model="fixed",
        borrow_annual_rate=0.03,
    )
    assert result.turnover == pytest.approx(0.0)
    assert result.impact_cost == pytest.approx(0.0)
    assert result.borrow_cost > 0


def test_borrow_is_charged_on_the_achieved_book_not_the_requested_one():
    # The cap stops the short from being fully established, so the borrow charge
    # must be on what was actually shorted.
    result, _ = rebalance_cost(
        _w(A=-0.50), _w(A=0.0), capital=1_000_000.0, periods_per_year=252,
        adv_value=_w(A=1_000_000.0), impact_model="fixed", borrow_annual_rate=0.10,
    )
    assert result.borrow_cost == pytest.approx(0.10 * 0.10 / 252)
