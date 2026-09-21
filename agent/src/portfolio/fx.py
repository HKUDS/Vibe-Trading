"""FX conversion for portfolio valuation.

Rates are expressed as currency units per USD. Currency identity and rate
availability are deliberately separate: a valid ISO currency may still be
unrateable by the current production FX feed, in which case valuation fails
closed with the missing currency named.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from src.portfolio.compatibility import PortfolioContractError

Rates = Mapping[str, Decimal]

DISPLAY_RATE_CURRENCIES = frozenset({"USD", "CNY", "HKD"})


def _validated_rate(pair: str, value: Decimal) -> Decimal:
    """Return a finite positive FX rate or fail closed naming its pair."""
    rate = Decimal(value)
    if not rate.is_finite() or rate <= 0:
        raise PortfolioContractError(f"invalid FX rate for {pair}: {value}")
    return rate


def build_rates(usd_cny: Decimal, usd_hkd: Decimal) -> dict[str, Decimal]:
    """Build the production rates map, anchored on one USD."""
    return {
        "USD": Decimal("1"),
        "CNY": _validated_rate("USD/CNY", usd_cny),
        "HKD": _validated_rate("USD/HKD", usd_hkd),
    }


def to_usd(value: Decimal, currency: str, rates: Rates) -> Decimal:
    """Convert value into USD, failing closed when a rate is unavailable."""
    code = str(currency or "").upper()
    rate = rates.get(code)
    if rate is None:
        raise PortfolioContractError(
            f"portfolio FX conversion is not available for: {code}"
        )
    rate = _validated_rate(f"USD/{code}", rate)
    return value / rate


def from_usd(value_usd: Decimal, currency: str, rates: Rates) -> Decimal:
    """Convert a USD value into currency, failing closed on a rate gap."""
    code = str(currency or "").upper()
    rate = rates.get(code)
    if rate is None:
        raise PortfolioContractError(
            f"portfolio FX conversion is not available for: {code}"
        )
    rate = _validated_rate(f"USD/{code}", rate)
    return value_usd * rate
