"""Tests for the market-impact and slippage models.

Two properties matter more than any single number and are asserted for all three
price models: impact is monotone in order size, and it vanishes at zero size.
"""

from __future__ import annotations

import itertools
import math

import pandas as pd
import pytest

from src.quantlib.impact import (
    DEFAULT_DELAY_BARS,
    DEFAULT_LINEAR_IMPACT_COEFF,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_SQRT_IMPACT_ETA,
    delayed_execution,
    fixed_slippage,
    linear_impact,
    sqrt_impact,
)

PRICE = 100.0
ADV = 1_000_000.0
VOLATILITY = 0.02

#: The three price models reduced to a common (price, direction, size) signature.
SIZED_MODELS = {
    "linear": lambda size, direction: linear_impact(PRICE, direction, size, ADV),
    "sqrt": lambda size, direction: sqrt_impact(PRICE, direction, size, ADV, VOLATILITY),
}


def test_fixed_slippage_matches_its_definition():
    """5bp on a price of 100 is exactly 0.05."""
    assert fixed_slippage(PRICE, 1, bps=5.0) == pytest.approx(100.05, abs=1e-12)
    assert fixed_slippage(PRICE, -1, bps=5.0) == pytest.approx(99.95, abs=1e-12)


def test_defaults_are_wired_to_the_module_constants():
    """Each default argument really is its constant, not a re-typed literal."""
    assert fixed_slippage(PRICE, 1) == fixed_slippage(PRICE, 1, bps=DEFAULT_SLIPPAGE_BPS)
    assert linear_impact(PRICE, 1, 100_000.0, ADV) == linear_impact(
        PRICE, 1, 100_000.0, ADV, impact_coeff=DEFAULT_LINEAR_IMPACT_COEFF
    )
    assert sqrt_impact(PRICE, 1, 100_000.0, ADV, VOLATILITY) == sqrt_impact(
        PRICE, 1, 100_000.0, ADV, VOLATILITY, eta=DEFAULT_SQRT_IMPACT_ETA
    )


def test_default_constants_hold_the_values_the_skill_documents():
    """Pin the published numbers.

    ``skills/execution-model/SKILL.md`` tells readers that ``bps`` defaults to 5.0,
    ``impact_coeff`` to 0.1, ``eta`` to 0.5 and ``delay_bars`` to 1. Comparing a
    default against its own constant cannot catch a change to that constant, so the
    values are asserted literally here -- otherwise a silent edit would leave the
    suite green and the documentation wrong.
    """
    assert DEFAULT_SLIPPAGE_BPS == 5.0
    assert DEFAULT_LINEAR_IMPACT_COEFF == 0.1
    assert DEFAULT_SQRT_IMPACT_ETA == 0.5
    assert DEFAULT_DELAY_BARS == 1


def test_fixed_slippage_charges_regardless_of_size():
    """Unlike the sized models, the fixed model has no zero-impact limit.

    The module docstring used to claim every price model returns the untouched
    price at zero size. It does not hold for this one, which takes no size at all.
    """
    assert fixed_slippage(PRICE, 1) - PRICE == pytest.approx(PRICE * DEFAULT_SLIPPAGE_BPS / 10_000.0, abs=1e-12)
    with pytest.raises(TypeError):
        fixed_slippage(PRICE, 1, 5.0, 0.0)  # no size parameter exists to pass


def test_fixed_slippage_zero_bps_is_free():
    """Zero basis points leaves the price untouched."""
    assert fixed_slippage(PRICE, 1, bps=0.0) == PRICE
    assert fixed_slippage(PRICE, -1, bps=0.0) == PRICE


def test_linear_impact_matches_its_definition():
    """10% participation at coeff 0.1 is a 1% price move."""
    assert linear_impact(PRICE, 1, 100_000.0, ADV, impact_coeff=0.1) == pytest.approx(101.0, abs=1e-12)
    assert linear_impact(PRICE, -1, 100_000.0, ADV, impact_coeff=0.1) == pytest.approx(99.0, abs=1e-12)


def test_sqrt_impact_matches_its_definition():
    """eta * sigma * sqrt(participation) = 0.5 * 0.02 * sqrt(0.25) = 0.005."""
    price = sqrt_impact(PRICE, 1, 250_000.0, ADV, VOLATILITY, eta=0.5)
    assert price == pytest.approx(PRICE * (1.0 + 0.5 * 0.02 * math.sqrt(0.25)), abs=1e-12)
    assert price == pytest.approx(100.5, abs=1e-12)


@pytest.mark.parametrize("name", sorted(SIZED_MODELS))
@pytest.mark.parametrize("direction", [1, -1])
def test_zero_size_limit_is_zero_impact(name, direction):
    """A zero-size order moves the price not at all."""
    assert SIZED_MODELS[name](0.0, direction) == pytest.approx(PRICE, abs=1e-12)


@pytest.mark.parametrize("name", sorted(SIZED_MODELS))
def test_impact_is_monotone_in_size_when_buying(name):
    """Buying more pushes the fill price strictly higher."""
    model = SIZED_MODELS[name]
    sizes = [0.0, 1_000.0, 10_000.0, 100_000.0, 250_000.0, 500_000.0]
    prices = [model(size, 1) for size in sizes]
    assert all(later > earlier for earlier, later in itertools.pairwise(prices))


@pytest.mark.parametrize("name", sorted(SIZED_MODELS))
def test_impact_is_monotone_in_size_when_selling(name):
    """Selling more pushes the fill price strictly lower."""
    model = SIZED_MODELS[name]
    sizes = [0.0, 1_000.0, 10_000.0, 100_000.0, 250_000.0, 500_000.0]
    prices = [model(size, -1) for size in sizes]
    assert all(later < earlier for earlier, later in itertools.pairwise(prices))


@pytest.mark.parametrize("name", sorted(SIZED_MODELS))
@pytest.mark.parametrize("direction", [1, -1])
def test_impact_always_works_against_the_trader(name, direction):
    """Buys never fill below the reference price, sells never fill above it."""
    filled = SIZED_MODELS[name](200_000.0, direction)
    assert (filled - PRICE) * direction > 0.0


def test_sqrt_marginal_impact_decays_but_linear_marginal_impact_does_not():
    """The square-root model's whole point: each extra share costs less than the last."""
    step = 100_000.0
    sqrt_first = sqrt_impact(PRICE, 1, step, ADV, VOLATILITY) - PRICE
    sqrt_second = sqrt_impact(PRICE, 1, 2 * step, ADV, VOLATILITY) - sqrt_impact(PRICE, 1, step, ADV, VOLATILITY)
    assert sqrt_second < sqrt_first

    linear_first = linear_impact(PRICE, 1, step, ADV) - PRICE
    linear_second = linear_impact(PRICE, 1, 2 * step, ADV) - linear_impact(PRICE, 1, step, ADV)
    assert linear_second == pytest.approx(linear_first, abs=1e-12)


def test_impact_scales_with_its_coefficients():
    """Doubling the coefficient doubles the impact for both sized models."""
    base = linear_impact(PRICE, 1, 100_000.0, ADV, impact_coeff=0.1) - PRICE
    assert linear_impact(PRICE, 1, 100_000.0, ADV, impact_coeff=0.2) - PRICE == pytest.approx(2 * base, abs=1e-12)

    sqrt_base = sqrt_impact(PRICE, 1, 100_000.0, ADV, VOLATILITY, eta=0.4) - PRICE
    doubled = sqrt_impact(PRICE, 1, 100_000.0, ADV, VOLATILITY, eta=0.8) - PRICE
    assert doubled == pytest.approx(2 * sqrt_base, abs=1e-12)


def test_zero_volatility_means_no_sqrt_impact():
    """With no volatility the square-root model charges nothing."""
    assert sqrt_impact(PRICE, 1, 500_000.0, ADV, 0.0) == pytest.approx(PRICE, abs=1e-12)


@pytest.mark.parametrize("direction", [0, 2, -2, 0.5, "buy", None])
def test_bad_direction_is_rejected(direction):
    """Direction multiplies the impact, so anything but 1 or -1 must raise."""
    with pytest.raises(ValueError, match="direction"):
        fixed_slippage(PRICE, direction)


def test_numerically_equal_direction_is_accepted():
    """1.0 and True equal 1, so the membership test accepts them; that is intended."""
    assert fixed_slippage(PRICE, 1.0) == fixed_slippage(PRICE, 1)
    assert fixed_slippage(PRICE, True) == fixed_slippage(PRICE, 1)


@pytest.mark.parametrize("price", [0.0, -1.0])
def test_non_positive_price_is_rejected(price):
    """A non-positive reference price is nonsense for every model."""
    with pytest.raises(ValueError, match="price"):
        fixed_slippage(price, 1)
    with pytest.raises(ValueError, match="price"):
        linear_impact(price, 1, 1_000.0, ADV)
    with pytest.raises(ValueError, match="price"):
        sqrt_impact(price, 1, 1_000.0, ADV, VOLATILITY)


def test_zero_adv_is_rejected_rather_than_dividing_by_zero():
    """An instrument that does not trade has no defined participation rate."""
    with pytest.raises(ValueError, match="adv"):
        linear_impact(PRICE, 1, 1_000.0, 0.0)
    with pytest.raises(ValueError, match="adv"):
        sqrt_impact(PRICE, 1, 1_000.0, 0.0, VOLATILITY)


def test_negative_size_is_rejected():
    """Side is carried by direction, so a negative size is a caller bug."""
    with pytest.raises(ValueError, match="volume_traded"):
        linear_impact(PRICE, 1, -1_000.0, ADV)
    with pytest.raises(ValueError, match="volume_traded"):
        sqrt_impact(PRICE, 1, -1_000.0, ADV, VOLATILITY)


def test_negative_coefficients_are_rejected():
    """A negative coefficient would pay the trader for trading."""
    with pytest.raises(ValueError, match="bps"):
        fixed_slippage(PRICE, 1, bps=-1.0)
    with pytest.raises(ValueError, match="impact_coeff"):
        linear_impact(PRICE, 1, 1_000.0, ADV, impact_coeff=-0.1)
    with pytest.raises(ValueError, match="eta"):
        sqrt_impact(PRICE, 1, 1_000.0, ADV, VOLATILITY, eta=-0.5)
    with pytest.raises(ValueError, match="volatility"):
        sqrt_impact(PRICE, 1, 1_000.0, ADV, -0.02)


def test_delayed_execution_shifts_the_signal_forward():
    """A one-bar delay moves each value to the next bar and blanks the first."""
    signal = pd.Series([1.0, 0.0, -1.0, 1.0])
    delayed = delayed_execution(signal, delay_bars=1)
    assert math.isnan(delayed.iloc[0])
    assert list(delayed.iloc[1:]) == [1.0, 0.0, -1.0]


def test_delayed_execution_default_is_t_plus_one():
    """The default lag is one bar, matching the China A-share T+1 rule."""
    signal = pd.Series([1.0, 2.0, 3.0])
    pd.testing.assert_series_equal(delayed_execution(signal), delayed_execution(signal, delay_bars=1))


def test_zero_delay_returns_an_equal_signal():
    """Zero delay is same-bar execution and changes nothing."""
    signal = pd.Series([1.0, 0.0, -1.0])
    pd.testing.assert_series_equal(delayed_execution(signal, delay_bars=0), signal)


def test_delayed_execution_preserves_the_index():
    """The index must survive so the signal still aligns with its price frame."""
    index = pd.date_range("2024-01-01", periods=4, freq="D")
    signal = pd.Series([1.0, 0.0, -1.0, 1.0], index=index)
    pd.testing.assert_index_equal(delayed_execution(signal).index, index)


def test_negative_delay_is_rejected_as_lookahead_bias():
    """A negative shift pulls future signal into the past; that must never be silent."""
    with pytest.raises(ValueError, match="look-ahead"):
        delayed_execution(pd.Series([1.0, 2.0]), delay_bars=-1)


def test_delayed_execution_rejects_a_non_series():
    """A DataFrame or list would shift with different semantics, so reject it."""
    with pytest.raises(TypeError, match="pandas Series"):
        delayed_execution([1.0, 2.0, 3.0])
