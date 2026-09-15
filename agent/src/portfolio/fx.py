"""FX conversion for portfolio valuation, decoupled from currency validation.

A ``Rates`` map says how many units of a currency one USD buys (``usd_cny``
of 7.2 means 7.2 CNY per USD). Valid ISO currencies pass validation on their
own; conversion to or from USD fails closed with a named gap when the pair is
missing, instead of silently pricing unknown currencies as USD.
"""

from decimal import Decimal
from typing import Mapping

from src.portfolio.compatibility import PortfolioContractError

Rates = Mapping[str, Decimal]


def build_rates(usd_cny: Decimal, usd_hkd: Decimal) -> dict[str, Decimal]:
    """Rates the default FX fetcher guarantees today, anchored on USD."""
    return {"USD": Decimal("1"), "CNY": usd_cny, "HKD": usd_hkd}


def to_usd(value: Decimal, currency: str, rates: Rates) -> Decimal:
    """Convert ``value`` of ``currency`` into USD, failing closed on a gap."""
    currency = currency.upper()
    rate = rates.get(currency)
    if rate is None or rate == 0:
        raise PortfolioContractError(
            f"portfolio FX conversion is not available for: {currency}"
        )
    return value / rate


def from_usd(value_usd: Decimal, currency: str, rates: Rates) -> Decimal:
    """Convert a USD value into ``currency``, failing closed on a gap."""
    currency = currency.upper()
    rate = rates.get(currency)
    if rate is None or rate == 0:
        raise PortfolioContractError(
            f"portfolio FX conversion is not available for: {currency}"
        )
    return value_usd * rate
