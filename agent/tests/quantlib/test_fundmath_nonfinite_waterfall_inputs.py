"""Non-finite hurdle and waterfall inputs must raise, not mis-split profit."""

from __future__ import annotations

import math
from datetime import date

import pytest

from src.entities.cashflow import CashFlow, CashFlowSeries
from src.quantlib.fundmath import european_waterfall, preferred_return_amount, waterfall_split


def _series() -> CashFlowSeries:
    return CashFlowSeries(
        (
            CashFlow(date(2020, 1, 1), -100.0, "contribution", "USD"),
            CashFlow(date(2025, 1, 1), 300.0, "distribution", "USD"),
        )
    )


@pytest.mark.parametrize("rate", [math.nan, math.inf])
def test_non_finite_preferred_rate_raises(rate: float) -> None:
    with pytest.raises(ValueError, match="preferred rate"):
        preferred_return_amount(_series(), rate=rate)
    with pytest.raises(ValueError, match="preferred rate"):
        european_waterfall(_series(), preferred_rate=rate, carry_rate=0.2)


@pytest.mark.parametrize("days_per_year", [math.nan, math.inf])
def test_non_finite_day_basis_raises(days_per_year: float) -> None:
    with pytest.raises(ValueError, match="days_per_year"):
        preferred_return_amount(_series(), rate=0.08, days_per_year=days_per_year)


@pytest.mark.parametrize(
    "amounts",
    [
        (math.nan, 100.0, 8.0),
        (150.0, math.nan, 8.0),
        (150.0, 100.0, math.nan),
        (150.0, 100.0, math.inf),
    ],
)
def test_non_finite_waterfall_amounts_raise(amounts: tuple[float, float, float]) -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        waterfall_split(*amounts, carry_rate=0.2)


def test_finite_inputs_keep_their_split() -> None:
    result = european_waterfall(_series(), preferred_rate=0.08, carry_rate=0.2)
    assert result.gp_total > 0.0
    assert math.isclose(result.lp_total + result.gp_total, 300.0)
