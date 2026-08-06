"""Trading-cost model for factor backtests: ADV caps, impact, borrow.

A long-short factor backtest that rebalances daily on a 500-name universe is
implicitly claiming it can trade every name, in any size, at the close, for a
flat fee. Three things break that claim, and this module prices all three:

**Capacity.** You cannot buy more of a stock in a day than the market trades.
The standard bound is a participation rate -- a fraction of average daily volume
you are willing to be. Beyond it you are the market, not a participant in it.
When a target weight needs more than the cap allows, the position moves *part of
the way* and the shortfall carries into the next period. It is not silently
filled, and it is not silently dropped: both would flatter the backtest, in
opposite directions.

**Impact.** The part you do trade moves the price against you, and the amount is
not linear in size. :mod:`src.quantlib.impact` already owns those models --
this module calls them rather than carrying a second copy.

**Borrow.** The short leg is not free. Someone lends you the stock and charges
for it, and for hard-to-borrow names that fee can exceed the alpha. A long-short
factor reported without borrow cost is reporting a portfolio nobody could have
held.

WHY THIS IS NOT IN THE ENGINE
-----------------------------
``backtest/engines/base.py`` prices costs per *fill*, which is the right model
when there is an order book and a fill sequence. A factor bench has neither: it
has a weight vector per rebalance date. Forcing one abstraction onto the other
would mean inventing fills that never happened. This module therefore works in
weight space, and the two never share a code path.

SIGN AND UNIT CONVENTIONS
-------------------------
* Weights are fractions of capital; a short is negative.
* Every cost this module returns is a POSITIVE drag, to be subtracted from a
  gross return. A function that returned a signed adjustment would eventually be
  added somewhere by mistake.
* ``adv`` is in the same currency as ``capital``, not in shares. Mixing those is
  the classic error here, so the argument names say ``_value`` and the
  docstrings repeat it.
* Rates named ``annual_*`` are annualised decimals; the periods-per-year
  argument converts them, and it has no default because a daily and a monthly
  bench would silently differ by 21x.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.quantlib.impact import DEFAULT_SLIPPAGE_BPS, linear_impact, sqrt_impact

__all__ = [
    "DEFAULT_MAX_PARTICIPATION",
    "IMPACT_MODELS",
    "MARKET_BORROW_RATES",
    "CapacityResult",
    "PeriodCost",
    "apply_adv_capacity",
    "borrow_cost",
    "rebalance_cost",
]

#: Fraction of a name's average daily value a strategy is allowed to be. 10% is
#: the conventional institutional ceiling; above it the participation itself
#: starts to define the price and the impact models stop being descriptive.
DEFAULT_MAX_PARTICIPATION: float = 0.10

#: Impact models callable by name. Both come from ``src.quantlib.impact``; this
#: module owns no impact formula of its own.
IMPACT_MODELS: tuple[str, ...] = ("fixed", "linear", "sqrt")

#: Indicative annual stock-borrow rates for a general-collateral name, by
#: market. These are STARTING POINTS for a caller who has no better number, not
#: measurements: a hard-to-borrow name can cost 20% or more, and nothing in this
#: repository knows which names those are. Pass your own rate when you have one.
MARKET_BORROW_RATES: dict[str, float] = {
    "US": 0.0030,
    "CN": 0.0850,
    "HK": 0.0100,
    "JP": 0.0050,
}


@dataclass(frozen=True)
class CapacityResult:
    """Weights actually achievable under an ADV participation cap.

    Attributes:
        achieved_weights: Weights after capping, indexed by symbol.
        requested_weights: The weights that were asked for.
        unfilled_weights: ``requested - achieved`` per symbol. Non-zero means
            the strategy wanted a position the market could not give it that
            period; carry this into the next rebalance rather than discarding it.
        capped_symbols: Symbols whose trade hit the cap.
        participation: Realised participation per symbol, as a fraction of ADV.
        max_participation: The cap that was applied.
    """

    achieved_weights: pd.Series
    requested_weights: pd.Series
    unfilled_weights: pd.Series
    capped_symbols: tuple[str, ...]
    participation: pd.Series
    max_participation: float


@dataclass(frozen=True)
class PeriodCost:
    """All-in trading drag for one rebalance period.

    Attributes:
        impact_cost: Drag from market impact and spread, as a fraction of
            capital. Positive.
        borrow_cost: Drag from borrowing the short leg, as a fraction of
            capital. Positive.
        total_cost: ``impact_cost + borrow_cost``. Positive.
        turnover: One-way turnover actually executed, as a fraction of capital.
        unfilled_turnover: Turnover the ADV cap prevented.
        capped_symbols: Symbols that hit the cap.
        impact_model: Which model priced the impact.
    """

    impact_cost: float
    borrow_cost: float
    total_cost: float
    turnover: float
    unfilled_turnover: float
    capped_symbols: tuple[str, ...]
    impact_model: str


def _as_aligned(
    target: pd.Series, current: pd.Series
) -> tuple[pd.Series, pd.Series, pd.Index]:
    """Put two weight vectors on one index, filling absent names with zero.

    A name in the target but not the current book is a new position; a name in
    the current book but not the target is a full exit. Both are trades, so
    neither may be dropped by an inner join.

    Args:
        target: Desired weights.
        current: Weights held before the rebalance.

    Returns:
        Tuple of ``(target, current, index)`` on the union index.
    """
    index = target.index.union(current.index)
    return (
        target.reindex(index).fillna(0.0).astype(float),
        current.reindex(index).fillna(0.0).astype(float),
        index,
    )


def apply_adv_capacity(
    target_weights: pd.Series,
    current_weights: pd.Series,
    adv_value: pd.Series,
    capital: float,
    max_participation: float = DEFAULT_MAX_PARTICIPATION,
) -> CapacityResult:
    """Cap each name's trade at a fraction of its average daily traded value.

    Args:
        target_weights: Desired weights by symbol, shorts negative.
        current_weights: Weights held before this rebalance.
        adv_value: Average daily traded VALUE by symbol, in the same currency as
            ``capital`` -- not a share count.
        capital: Portfolio capital in that currency.
        max_participation: Largest fraction of a name's ADV the strategy may be.

    Returns:
        A :class:`CapacityResult`. A symbol with no ADV entry, or a non-positive
        one, is treated as untradeable this period: its weight stays where it
        was and the whole requested change lands in ``unfilled_weights``. That
        is deliberately the conservative reading -- assuming a name with unknown
        volume is infinitely liquid is how a backtest acquires capacity it never
        had.

    Raises:
        ValueError: If ``capital`` is not positive or ``max_participation`` is
            outside ``(0, 1]``.
    """
    if not capital > 0:
        raise ValueError(f"capital must be positive, got {capital}")
    if not 0.0 < max_participation <= 1.0:
        raise ValueError(
            f"max_participation must be in (0, 1], got {max_participation}"
        )

    target, current, index = _as_aligned(target_weights, current_weights)
    adv = pd.Series(adv_value, dtype=float).reindex(index)

    requested_change = target - current
    # Largest weight change a name can absorb: participation x ADV, expressed
    # as a fraction of capital.
    capacity = (adv * max_participation / capital).fillna(0.0)
    capacity[~np.isfinite(capacity)] = 0.0
    capacity[capacity < 0.0] = 0.0

    allowed_change = requested_change.clip(lower=-capacity, upper=capacity)
    achieved = current + allowed_change
    unfilled = target - achieved

    capped = tuple(
        str(sym)
        for sym in index
        if abs(requested_change[sym]) > capacity[sym] + 1e-15
        and abs(requested_change[sym]) > 0.0
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        participation = (allowed_change.abs() * capital / adv).replace(
            [np.inf, -np.inf], np.nan
        )

    return CapacityResult(
        achieved_weights=achieved,
        requested_weights=target,
        unfilled_weights=unfilled,
        capped_symbols=capped,
        participation=participation,
        max_participation=max_participation,
    )


def borrow_cost(
    weights: pd.Series,
    periods_per_year: int,
    annual_rate: float | pd.Series | None = None,
    market: str | None = None,
) -> float:
    """Cost of borrowing the short leg for one period.

    Only negative weights are charged: a long position borrows nothing. The
    charge is the absolute short exposure times the pro-rated annual fee.

    Args:
        weights: Portfolio weights, shorts negative.
        periods_per_year: Rebalance periods in a year -- 252 for daily, 12 for
            monthly. No default: a daily and a monthly bench charging the same
            per-period rate differ by 21x, and nothing downstream would notice.
        annual_rate: Annual borrow fee as a decimal, either one rate for the
            whole book or a per-symbol Series. Takes precedence over ``market``.
        market: Key into :data:`MARKET_BORROW_RATES` when no explicit rate is
            supplied. Those values are indicative general-collateral rates, not
            measurements -- see the constant's own note.

    Returns:
        Positive cost as a fraction of capital.

    Raises:
        ValueError: If ``periods_per_year`` is not positive, if neither
            ``annual_rate`` nor ``market`` is supplied, if ``market`` is
            unknown, or if any rate is negative.
    """
    if periods_per_year <= 0:
        raise ValueError(f"periods_per_year must be positive, got {periods_per_year}")

    if annual_rate is None:
        if market is None:
            raise ValueError(
                "supply annual_rate, or market to fall back on an indicative "
                f"general-collateral rate from {sorted(MARKET_BORROW_RATES)}"
            )
        if market not in MARKET_BORROW_RATES:
            raise ValueError(
                f"unknown market {market!r}; known: {sorted(MARKET_BORROW_RATES)}"
            )
        annual_rate = MARKET_BORROW_RATES[market]

    shorts = pd.Series(weights, dtype=float)
    shorts = -shorts[shorts < 0.0]
    if shorts.empty:
        return 0.0

    if isinstance(annual_rate, pd.Series):
        rates = annual_rate.reindex(shorts.index)
        if rates.isna().any():
            missing = sorted(str(s) for s in rates.index[rates.isna()])
            raise ValueError(
                f"annual_rate is missing a rate for shorted symbol(s): {missing}"
            )
    else:
        rates = pd.Series(float(annual_rate), index=shorts.index)

    if (rates < 0.0).any():
        raise ValueError("borrow rates must be non-negative")

    return float((shorts * rates).sum() / periods_per_year)


def rebalance_cost(
    target_weights: pd.Series,
    current_weights: pd.Series,
    capital: float,
    periods_per_year: int,
    adv_value: pd.Series | None = None,
    max_participation: float = DEFAULT_MAX_PARTICIPATION,
    impact_model: str = "sqrt",
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    impact_coefficient: float = 0.1,
    volatility: float | pd.Series | None = None,
    borrow_annual_rate: float | pd.Series | None = None,
    borrow_market: str | None = None,
) -> tuple[PeriodCost, CapacityResult | None]:
    """Price one rebalance: capacity, then impact, then borrow.

    Args:
        target_weights: Desired weights, shorts negative.
        current_weights: Weights held before the rebalance.
        capital: Portfolio capital.
        periods_per_year: Rebalance periods in a year, for the borrow charge.
        adv_value: Average daily traded VALUE by symbol. When None, no capacity
            cap is applied and ``capped_symbols`` comes back empty -- which is
            an assumption of infinite liquidity and should be stated wherever
            the result is reported.
        max_participation: Participation ceiling for the capacity cap.
        impact_model: One of :data:`IMPACT_MODELS`.
        slippage_bps: Half-spread plus fees, in basis points, charged on every
            unit of turnover regardless of model.
        impact_coefficient: Coefficient handed to the linear or sqrt model.
        volatility: Per-period volatility, required by the ``sqrt`` model.
        borrow_annual_rate: Annual borrow fee, decimal.
        borrow_market: Fallback market key when no explicit rate is given.

    Returns:
        Tuple of the :class:`PeriodCost` and the :class:`CapacityResult` (None
        when no ``adv_value`` was supplied).

    Raises:
        ValueError: If ``impact_model`` is unknown, if the ``sqrt`` model is
            chosen without ``volatility``, or from the functions this delegates
            to.
    """
    if impact_model not in IMPACT_MODELS:
        raise ValueError(
            f"impact_model must be one of {IMPACT_MODELS}, got {impact_model!r}"
        )

    target, current, index = _as_aligned(target_weights, current_weights)

    capacity: CapacityResult | None = None
    if adv_value is not None:
        capacity = apply_adv_capacity(
            target, current, adv_value, capital, max_participation
        )
        achieved = capacity.achieved_weights
        unfilled_turnover = float(capacity.unfilled_weights.abs().sum())
        capped = capacity.capped_symbols
    else:
        achieved = target
        unfilled_turnover = 0.0
        capped = ()

    traded = (achieved - current).abs()
    turnover = float(traded.sum())

    # Spread and fees are charged on every unit of turnover under every model.
    spread_cost = turnover * slippage_bps / 10_000.0

    if impact_model == "fixed" or turnover == 0.0:
        impact = 0.0
    elif impact_model == "linear":
        participation = (
            capacity.participation.reindex(index).fillna(0.0)
            if capacity is not None
            else pd.Series(0.0, index=index)
        )
        # linear_impact prices a fill; here it prices the weighted average
        # participation, and the drag scales with the traded fraction.
        impact = float((traded * participation * impact_coefficient).sum())
    else:  # sqrt
        if volatility is None:
            raise ValueError(
                "the sqrt impact model needs a volatility; supply one or choose "
                "impact_model='linear' or 'fixed'"
            )
        vol = (
            pd.Series(volatility, dtype=float).reindex(index).fillna(0.0)
            if isinstance(volatility, pd.Series)
            else pd.Series(float(volatility), index=index)
        )
        participation = (
            capacity.participation.reindex(index).fillna(0.0)
            if capacity is not None
            else pd.Series(0.0, index=index)
        )
        impact = float(
            (traded * impact_coefficient * vol * np.sqrt(participation.clip(lower=0.0))).sum()
        )

    impact_cost = spread_cost + impact
    borrow = borrow_cost(
        achieved,
        periods_per_year=periods_per_year,
        annual_rate=borrow_annual_rate,
        market=borrow_market,
    ) if (borrow_annual_rate is not None or borrow_market is not None) else 0.0

    return (
        PeriodCost(
            impact_cost=impact_cost,
            borrow_cost=borrow,
            total_cost=impact_cost + borrow,
            turnover=turnover,
            unfilled_turnover=unfilled_turnover,
            capped_symbols=capped,
            impact_model=impact_model,
        ),
        capacity,
    )
