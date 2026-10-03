"""Bracket fallback must honor the same price tolerance as Newton."""

import math

import pytest

from src.quantlib.options import bs_price, implied_volatility


@pytest.mark.parametrize("scale", [1.0, 100.0, 10000.0])
def test_implied_volatility_fallback_reprices_within_absolute_tolerance(
    scale: float,
) -> None:
    spot, strike, maturity, rate, volatility = (
        100.0 * scale,
        150.0 * scale,
        1.0,
        0.05,
        0.2,
    )
    quote = bs_price(spot, strike, maturity, rate, volatility)
    tolerance = 1e-6
    implied = implied_volatility(quote, spot, strike, maturity, rate, tol=tolerance)
    assert math.isfinite(implied)
    assert abs(bs_price(spot, strike, maturity, rate, implied) - quote) < tolerance
