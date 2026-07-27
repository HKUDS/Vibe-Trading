"""Options Lab payoff explorer backend.

Deterministic payoff and scenario math for multi-leg option strategies,
independent of any market data feed: hand it legs and a spot grid and it
hands back the expiry payoff curve, breakevens, and a spot x IV scenario
grid. Legs without an explicit premium are priced with the same
Black-Scholes the backtest engine uses, so what-if results line up with
what the engine would have charged at entry.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backtest.engines.options_portfolio import bs_price

_BREAKEVEN_GRID_POINTS = 2001


@dataclass(frozen=True)
class OptionLeg:
    option_type: str  # "call" | "put"
    strike: float
    qty: int  # >0 long, <0 short
    premium: float | None = None  # per share; None prices it with BS


@dataclass(frozen=True)
class PayoffReport:
    spot_grid: np.ndarray
    payoff: np.ndarray
    net_premium: float  # total entry cost in currency; negative is a credit
    breakevens: list[float]
    max_profit: float
    max_loss: float
    profit_unbounded: bool
    loss_unbounded: bool


def _intrinsic(option_type: str, spot: float, strike: float) -> float:
    if option_type == "call":
        return max(spot - strike, 0.0)
    return max(strike - spot, 0.0)


def _leg_premiums(
    legs: list[OptionLeg],
    entry_spot: float,
    time_to_expiry: float,
    rate: float,
    iv: float,
) -> np.ndarray:
    premiums = []
    for leg in legs:
        if leg.premium is not None:
            premiums.append(leg.premium)
        else:
            premiums.append(bs_price(entry_spot, leg.strike, time_to_expiry, rate, iv, leg.option_type))
    return np.asarray(premiums, dtype=float)


def expiry_payoff(
    legs: list[OptionLeg],
    spot_grid: np.ndarray,
    *,
    entry_spot: float,
    time_to_expiry: float,
    rate: float = 0.05,
    iv: float = 0.3,
    multiplier: float = 1.0,
) -> PayoffReport:
    """Expiry payoff curve for a strategy over a spot grid.

    Premiums are pinned at entry: explicit per-share premium when the leg
    carries one, otherwise the BS price at `entry_spot`. The payoff at every
    grid point is intrinsic value minus that pinned cost.
    """
    if not legs:
        raise ValueError("at least one leg is required")
    for leg in legs:
        if leg.option_type not in ("call", "put"):
            raise ValueError(f"unsupported option type: {leg.option_type}")

    premiums = _leg_premiums(legs, entry_spot, time_to_expiry, rate, iv)
    net_premium = float(sum(leg.qty * premium * multiplier for leg, premium in zip(legs, premiums, strict=True)))

    intrinsic = np.zeros(len(spot_grid))
    for leg in legs:
        intrinsic += leg.qty * np.array([_intrinsic(leg.option_type, float(s), leg.strike) for s in spot_grid])
    payoff = intrinsic * multiplier - net_premium

    # Analytic tails. Far right, each call pays (S-K): with net call qty the
    # S terms either grow without bound or cancel flat. Far left, puts pay
    # their strike and calls die, so the curve flattens to a finite value.
    # Fold those limits into the extrema instead of trusting the grid edges.
    net_call_qty = sum(leg.qty for leg in legs if leg.option_type == "call")
    profit_unbounded = net_call_qty > 0
    loss_unbounded = net_call_qty < 0

    left_tail = sum(leg.qty * leg.strike for leg in legs if leg.option_type == "put") * multiplier - net_premium
    if profit_unbounded:
        right_tail = float("inf")
    elif loss_unbounded:
        right_tail = float("-inf")
    else:
        right_tail = -sum(leg.qty * leg.strike for leg in legs if leg.option_type == "call") * multiplier - net_premium

    breakevens = _find_breakevens(spot_grid, payoff)
    max_profit = max(float(payoff.max()), left_tail, right_tail)
    max_loss = min(float(payoff.min()), left_tail, right_tail)
    return PayoffReport(
        spot_grid=spot_grid,
        payoff=payoff,
        net_premium=net_premium,
        breakevens=breakevens,
        max_profit=max_profit,
        max_loss=max_loss,
        profit_unbounded=profit_unbounded,
        loss_unbounded=loss_unbounded,
    )


def default_spot_grid(center: float, half_width_pct: float = 0.5) -> np.ndarray:
    """Symmetric grid around the entry spot, fine enough for breakeven roots."""
    lo = max(center * (1.0 - half_width_pct), 0.01)
    hi = center * (1.0 + half_width_pct)
    return np.linspace(lo, hi, _BREAKEVEN_GRID_POINTS)


def _find_breakevens(spot_grid: np.ndarray, payoff: np.ndarray) -> list[float]:
    roots: list[float] = []
    for i in range(len(spot_grid) - 1):
        y0, y1 = payoff[i], payoff[i + 1]
        if y0 == 0.0:
            roots.append(float(spot_grid[i]))
        elif y0 * y1 < 0:
            # Payoff is piecewise linear in spot, so linear interpolation
            # lands on the exact root.
            t = y0 / (y0 - y1)
            roots.append(float(spot_grid[i] + t * (spot_grid[i + 1] - spot_grid[i])))
    # dedupe adjacent hits when the curve sits exactly on zero at a grid point
    deduped: list[float] = []
    for root in roots:
        if not deduped or abs(root - deduped[-1]) > 1e-9:
            deduped.append(root)
    return deduped


def scenario_grid(
    legs: list[OptionLeg],
    spot_grid: np.ndarray,
    iv_values: np.ndarray,
    *,
    entry_spot: float,
    time_to_expiry: float,
    rate: float = 0.05,
    entry_iv: float = 0.3,
    multiplier: float = 1.0,
) -> np.ndarray:
    """Pre-expiry what-if PnL over (spot x IV), entry cost pinned at entry.

    Every cell reprices each leg with BS at that scenario's spot and IV and
    nets it against the premium paid at entry, so the (entry spot, entry IV)
    cell is zero by construction.
    """
    entry_premiums = _leg_premiums(legs, entry_spot, time_to_expiry, rate, entry_iv)
    net_premium = sum(leg.qty * premium * multiplier for leg, premium in zip(legs, entry_premiums, strict=True))

    grid = np.zeros((len(iv_values), len(spot_grid)))
    for iv_row, iv_now in enumerate(iv_values):
        for spot_col, spot_now in enumerate(spot_grid):
            value = 0.0
            for leg in legs:
                price_now = bs_price(
                    float(spot_now),
                    leg.strike,
                    time_to_expiry,
                    rate,
                    float(iv_now),
                    leg.option_type,
                )
                value += leg.qty * price_now * multiplier
            grid[iv_row, spot_col] = value - net_premium
    return grid


# --- Strategy presets ---


def bull_call_spread(lower_strike: float, upper_strike: float, qty: int = 1) -> list[OptionLeg]:
    if upper_strike <= lower_strike:
        raise ValueError("upper strike must sit above lower strike")
    return [
        OptionLeg("call", lower_strike, qty),
        OptionLeg("call", upper_strike, -qty),
    ]


def long_straddle(strike: float, qty: int = 1) -> list[OptionLeg]:
    return [OptionLeg("call", strike, qty), OptionLeg("put", strike, qty)]


def iron_condor(put_wing: float, put_body: float, call_body: float, call_wing: float, qty: int = 1) -> list[OptionLeg]:
    if not (put_wing < put_body < call_body < call_wing):
        raise ValueError("strikes must nest as put_wing < put_body < call_body < call_wing")
    return [
        OptionLeg("put", put_wing, qty),
        OptionLeg("put", put_body, -qty),
        OptionLeg("call", call_body, -qty),
        OptionLeg("call", call_wing, qty),
    ]
