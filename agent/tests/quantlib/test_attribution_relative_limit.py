"""Independent high-precision checks of the Carino near-coincidence limit."""

import pytest

from src.quantlib.attribution import carino_factor


@pytest.mark.parametrize(
    "portfolio_wealth,benchmark_wealth", [(1e-10, 2e-10), (1e-12, 8e-12)]
)
def test_carino_limit_is_relative_to_remaining_wealth(
    portfolio_wealth: float, benchmark_wealth: float
) -> None:
    """Small return differences near total loss need the logarithmic factor."""
    from decimal import Decimal, localcontext

    portfolio_return = portfolio_wealth - 1.0
    benchmark_return = benchmark_wealth - 1.0
    # Use exact supplied floats and independent high-precision logarithms.
    with localcontext() as ctx:
        ctx.prec = 60
        rp = Decimal.from_float(portfolio_return)
        rb = Decimal.from_float(benchmark_return)
        expected = float(((1 + rp).ln() - (1 + rb).ln()) / (rp - rb))
    assert carino_factor(portfolio_return, benchmark_return) == pytest.approx(
        expected, rel=1e-12
    )
