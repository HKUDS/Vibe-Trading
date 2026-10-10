"""Bracket fallback must honor the same price tolerance as Newton."""

import math

import pytest

from src.quantlib.options import bs_price, implied_volatility


@pytest.mark.parametrize("scale", [1.0, 100.0, 10000.0])
def test_implied_volatility_fallback_reprices_within_absolute_tolerance(
    scale: float, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.quantlib.options as options

    real_brentq = options.brentq
    calls = []

    def solve(*args, **kwargs):
        calls.append(kwargs)
        return real_brentq(*args, **kwargs)

    monkeypatch.setattr(options, "brentq", solve)
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
    assert len(calls) == 1
    assert math.isfinite(implied)
    assert abs(bs_price(spot, strike, maturity, rate, implied) - quote) < tolerance


def test_fallback_rejects_a_candidate_outside_price_tolerance(monkeypatch) -> None:
    import src.quantlib.options as options

    quote = bs_price(100.0, 150.0, 1.0, 0.05, 0.2)
    inaccurate = 0.2001
    assert abs(bs_price(100.0, 150.0, 1.0, 0.05, inaccurate) - quote) > 1e-6
    monkeypatch.setattr(options, "brentq", lambda *args, **kwargs: inaccurate)
    result = implied_volatility(quote, 100.0, 150.0, 1.0, 0.05)
    assert math.isnan(result)
