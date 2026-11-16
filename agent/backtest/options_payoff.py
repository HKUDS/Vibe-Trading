"""Deterministic payoff and scenario math for multi-leg option strategies.

The expiry summary is solved from the strategy's piecewise-linear payoff,
independently of the caller's display grid. This keeps breakevens and finite
extrema correct even when a chart grid omits one or more strikes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backtest.engines.options_portfolio import bs_price

_BREAKEVEN_TOLERANCE = 1e-9
_DEFAULT_GRID_POINTS = 2001


@dataclass(frozen=True)
class OptionLeg:
    """One European option leg in a payoff calculation.

    Attributes:
        option_type: ``"call"`` or ``"put"``.
        strike: Positive strike price.
        qty: Signed contract quantity; positive is long and negative is short.
        premium: Optional per-share entry premium. When omitted, Black-Scholes
            pricing is used at the supplied entry conditions.
    """

    option_type: str
    strike: float
    qty: int
    premium: float | None = None


@dataclass(frozen=True)
class PayoffReport:
    """Expiry payoff curve and analytic strategy summary.

    Attributes:
        spot_grid: Caller-supplied display spots.
        payoff: Expiry P&L at each display spot.
        net_premium: Signed gross entry premium; positive is a debit.
        entry_commission: Entry commission paid in account currency.
        entry_cost: Gross premium plus entry commission.
        breakevens: Isolated non-negative expiry spots where P&L is zero.
        breakeven_intervals: Continuous zero-P&L spot intervals. A ``None``
            upper bound represents a flat zero-payoff right tail.
        max_profit: Analytic maximum, or positive infinity when unbounded.
        max_loss: Analytic minimum P&L, or negative infinity when unbounded.
        profit_unbounded: Whether right-tail profit is unbounded.
        loss_unbounded: Whether right-tail loss is unbounded.
    """

    spot_grid: np.ndarray
    payoff: np.ndarray
    net_premium: float
    entry_commission: float
    entry_cost: float
    breakevens: list[float]
    breakeven_intervals: list[tuple[float, float | None]]
    max_profit: float
    max_loss: float
    profit_unbounded: bool
    loss_unbounded: bool


def _intrinsic(option_type: str, spots: np.ndarray, strike: float) -> np.ndarray:
    """Return vectorized intrinsic values for one option leg."""
    if option_type == "call":
        return np.maximum(spots - strike, 0.0)
    return np.maximum(strike - spots, 0.0)


def _validate_legs(legs: list[OptionLeg]) -> None:
    """Validate option-leg fields at the calculation boundary."""
    if not legs:
        raise ValueError("at least one leg is required")
    for index, leg in enumerate(legs):
        if leg.option_type not in ("call", "put"):
            raise ValueError(f"legs[{index}].option_type must be 'call' or 'put'")
        if not np.isfinite(leg.strike) or leg.strike <= 0:
            raise ValueError(f"legs[{index}].strike must be positive and finite")
        if isinstance(leg.qty, bool) or not isinstance(leg.qty, (int, np.integer)):
            raise ValueError(f"legs[{index}].qty must be a non-zero integer")
        if leg.qty == 0:
            raise ValueError(f"legs[{index}].qty must be non-zero")
        if leg.premium is not None and (not np.isfinite(leg.premium) or leg.premium < 0):
            raise ValueError(f"legs[{index}].premium must be non-negative and finite")


def _validate_market_inputs(
    *,
    entry_spot: float,
    time_to_expiry: float,
    rate: float,
    iv: float,
    multiplier: float,
    commission_rate: float,
) -> None:
    """Validate common market and cost inputs."""
    values = {
        "entry_spot": entry_spot,
        "time_to_expiry": time_to_expiry,
        "rate": rate,
        "iv": iv,
        "multiplier": multiplier,
        "commission_rate": commission_rate,
    }
    for name, value in values.items():
        if not np.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if entry_spot <= 0:
        raise ValueError("entry_spot must be positive")
    if time_to_expiry < 0:
        raise ValueError("time_to_expiry must be non-negative")
    if iv <= 0:
        raise ValueError("iv must be positive")
    if multiplier <= 0:
        raise ValueError("multiplier must be positive")
    if not 0 <= commission_rate < 1:
        raise ValueError("commission_rate must be in [0, 1)")


def _validate_grid(values: np.ndarray, *, name: str, allow_zero: bool) -> np.ndarray:
    """Return a validated one-dimensional numeric grid."""
    grid = np.asarray(values, dtype=float)
    if grid.ndim != 1 or grid.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional array")
    if not np.isfinite(grid).all():
        raise ValueError(f"{name} must contain only finite values")
    if allow_zero:
        invalid = grid < 0
    else:
        invalid = grid <= 0
    if invalid.any():
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} values must be {qualifier}")
    return grid


def _leg_premiums(
    legs: list[OptionLeg],
    entry_spot: float,
    time_to_expiry: float,
    rate: float,
    iv: float,
) -> np.ndarray:
    """Resolve explicit or Black-Scholes entry premiums for every leg."""
    premiums = []
    for leg in legs:
        premium = (
            leg.premium
            if leg.premium is not None
            else bs_price(
                entry_spot,
                leg.strike,
                time_to_expiry,
                rate,
                iv,
                leg.option_type,
            )
        )
        premiums.append(float(premium))
    return np.asarray(premiums, dtype=float)


def _entry_costs(
    legs: list[OptionLeg],
    premiums: np.ndarray,
    multiplier: float,
    commission_rate: float,
) -> tuple[float, float, float]:
    """Return gross premium, commission, and total signed entry cost."""
    net_premium = float(sum(leg.qty * premium * multiplier for leg, premium in zip(legs, premiums, strict=True)))
    entry_commission = float(
        sum(abs(leg.qty) * premium * multiplier * commission_rate for leg, premium in zip(legs, premiums, strict=True))
    )
    return net_premium, entry_commission, net_premium + entry_commission


def _payoff_at_spots(
    legs: list[OptionLeg],
    spots: np.ndarray,
    *,
    multiplier: float,
    entry_cost: float,
    underlying_qty: float = 0.0,
    entry_spot: float = 0.0,
) -> np.ndarray:
    """Calculate expiry P&L at arbitrary non-negative spots."""
    intrinsic = np.zeros(len(spots), dtype=float)
    for leg in legs:
        intrinsic += leg.qty * _intrinsic(leg.option_type, spots, leg.strike)
    return (intrinsic + underlying_qty * (spots - entry_spot)) * multiplier - entry_cost


def _critical_points(legs: list[OptionLeg]) -> np.ndarray:
    """Return every finite point at which expiry-payoff slope may change."""
    return np.asarray(sorted({0.0, *(float(leg.strike) for leg in legs)}))


def _analytic_breakevens(
    critical_spots: np.ndarray,
    critical_payoff: np.ndarray,
    right_slope: float,
) -> tuple[list[float], list[tuple[float, float | None]]]:
    """Solve isolated roots and continuous zero intervals analytically."""
    roots: list[float] = []
    intervals: list[tuple[float, float | None]] = []

    for index, (spot, value) in enumerate(zip(critical_spots, critical_payoff, strict=True)):
        if index == len(critical_spots) - 1:
            continue
        next_spot = float(critical_spots[index + 1])
        next_value = float(critical_payoff[index + 1])
        value = float(value)
        if abs(value) <= _BREAKEVEN_TOLERANCE and abs(next_value) <= _BREAKEVEN_TOLERANCE:
            intervals.append((float(spot), next_spot))
        elif value * next_value < 0:
            fraction = value / (value - next_value)
            roots.append(float(spot + fraction * (next_spot - spot)))

    right_spot = float(critical_spots[-1])
    right_value = float(critical_payoff[-1])
    if abs(right_slope) <= _BREAKEVEN_TOLERANCE and abs(right_value) <= _BREAKEVEN_TOLERANCE:
        intervals.append((right_spot, None))
    elif abs(right_slope) > _BREAKEVEN_TOLERANCE:
        right_root = right_spot - right_value / right_slope
        if right_root > right_spot + _BREAKEVEN_TOLERANCE:
            roots.append(float(right_root))

    intervals = _merge_zero_intervals(intervals)
    for spot, value in zip(critical_spots, critical_payoff, strict=True):
        spot = float(spot)
        if abs(float(value)) <= _BREAKEVEN_TOLERANCE and not _in_zero_interval(spot, intervals):
            roots.append(spot)

    roots.sort()
    deduped: list[float] = []
    for root in roots:
        if not deduped or abs(root - deduped[-1]) > _BREAKEVEN_TOLERANCE:
            deduped.append(root)
    return deduped, intervals


def _merge_zero_intervals(
    intervals: list[tuple[float, float | None]],
) -> list[tuple[float, float | None]]:
    """Merge adjacent continuous zero-payoff intervals."""
    merged: list[tuple[float, float | None]] = []
    for start, end in intervals:
        if not merged:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        if previous_end is not None and abs(previous_end - start) <= _BREAKEVEN_TOLERANCE:
            merged[-1] = (previous_start, end)
        else:
            merged.append((start, end))
    return merged


def _in_zero_interval(spot: float, intervals: list[tuple[float, float | None]]) -> bool:
    """Return whether a spot belongs to a continuous zero-payoff interval."""
    for start, end in intervals:
        if spot < start - _BREAKEVEN_TOLERANCE:
            continue
        if end is None or spot <= end + _BREAKEVEN_TOLERANCE:
            return True
    return False


def expiry_payoff(
    legs: list[OptionLeg],
    spot_grid: np.ndarray,
    *,
    entry_spot: float,
    time_to_expiry: float,
    rate: float = 0.05,
    iv: float = 0.3,
    multiplier: float = 1.0,
    commission_rate: float = 0.001,
    underlying_qty: float = 0.0,
) -> PayoffReport:
    """Calculate an expiry payoff curve and analytic risk summary.

    Premiums are pinned at entry. An explicit per-share premium wins over the
    Black-Scholes price. Entry commission follows the existing options engine:
    long legs pay ``premium * (1 + commission_rate)`` and short legs receive
    ``premium * (1 - commission_rate)``. Expiry settlement has no exit fee.

    Args:
        legs: Signed option legs in the strategy.
        spot_grid: Non-negative display spots. Summary values do not depend on
            this grid containing strikes or breakevens.
        entry_spot: Underlying spot at entry.
        time_to_expiry: Years until expiry at entry.
        rate: Annual continuously compounded risk-free rate.
        iv: Annualized volatility used for legs without explicit premiums.
        multiplier: Currency multiplier per option price unit.
        commission_rate: Entry commission as a fraction of gross premium.
        underlying_qty: Signed underlying units per multiplier; 1 with multiplier
            100 means 100 shares. No stock fees, funding or dividends modeled.

    Returns:
        Payoff report with the display curve and analytic extrema/breakevens.

    Raises:
        ValueError: If a leg, grid, market input, or cost input is invalid.
    """
    if not np.isfinite(underlying_qty):
        raise ValueError("underlying_qty must be finite")
    _validate_legs(legs)
    _validate_market_inputs(
        entry_spot=entry_spot,
        time_to_expiry=time_to_expiry,
        rate=rate,
        iv=iv,
        multiplier=multiplier,
        commission_rate=commission_rate,
    )
    display_spots = _validate_grid(spot_grid, name="spot_grid", allow_zero=True)
    premiums = _leg_premiums(legs, entry_spot, time_to_expiry, rate, iv)
    net_premium, entry_commission, entry_cost = _entry_costs(legs, premiums, multiplier, commission_rate)

    payoff = _payoff_at_spots(
        legs,
        display_spots,
        multiplier=multiplier,
        entry_cost=entry_cost,
        underlying_qty=underlying_qty,
        entry_spot=entry_spot,
    )

    critical_spots = _critical_points(legs)
    critical_payoff = _payoff_at_spots(
        legs,
        critical_spots,
        multiplier=multiplier,
        entry_cost=entry_cost,
        underlying_qty=underlying_qty,
        entry_spot=entry_spot,
    )
    right_slope = float((underlying_qty + sum(leg.qty for leg in legs if leg.option_type == "call")) * multiplier)
    profit_unbounded = right_slope > _BREAKEVEN_TOLERANCE
    loss_unbounded = right_slope < -_BREAKEVEN_TOLERANCE
    max_profit = float("inf") if profit_unbounded else float(np.max(critical_payoff))
    max_loss = float("-inf") if loss_unbounded else float(np.min(critical_payoff))
    breakevens, breakeven_intervals = _analytic_breakevens(critical_spots, critical_payoff, right_slope)

    return PayoffReport(
        spot_grid=display_spots,
        payoff=payoff,
        net_premium=net_premium,
        entry_commission=entry_commission,
        entry_cost=entry_cost,
        breakevens=breakevens,
        breakeven_intervals=breakeven_intervals,
        max_profit=max_profit,
        max_loss=max_loss,
        profit_unbounded=profit_unbounded,
        loss_unbounded=loss_unbounded,
    )


def default_spot_grid(
    center: float,
    half_width_pct: float = 0.5,
    points: int = _DEFAULT_GRID_POINTS,
) -> np.ndarray:
    """Build a symmetric non-negative display grid around an entry spot.

    Args:
        center: Positive central spot.
        half_width_pct: Fraction of ``center`` added to and subtracted from the
            bounds.
        points: Number of points, at least two.

    Returns:
        Increasing NumPy spot grid.

    Raises:
        ValueError: If a parameter is non-finite or outside its valid range.
    """
    if not np.isfinite(center) or center <= 0:
        raise ValueError("center must be positive and finite")
    if not np.isfinite(half_width_pct) or half_width_pct <= 0:
        raise ValueError("half_width_pct must be positive and finite")
    if isinstance(points, bool) or not isinstance(points, (int, np.integer)):
        raise ValueError("points must be an integer")
    if points < 2:
        raise ValueError("points must be at least 2")
    lower = max(center * (1.0 - half_width_pct), 0.0)
    upper = center * (1.0 + half_width_pct)
    return np.linspace(lower, upper, int(points))


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
    commission_rate: float = 0.001,
    underlying_qty: float = 0.0,
) -> np.ndarray:
    """Calculate pre-expiry mark-to-market P&L over spot and volatility.

    The entry cost is pinned once using the entry spot/IV and includes entry
    commission. Scenario values are marks, so no hypothetical closing
    commission is deducted.

    Args:
        legs: Signed option legs in the strategy.
        spot_grid: Non-negative scenario spots.
        iv_values: Positive annualized volatility scenarios.
        entry_spot: Underlying spot at entry.
        time_to_expiry: Years remaining in every scenario.
        rate: Annual continuously compounded risk-free rate.
        entry_iv: Annualized volatility used to price the entry.
        multiplier: Currency multiplier per option price unit.
        commission_rate: Entry commission as a fraction of gross premium.
        underlying_qty: Signed underlying units per multiplier; 1 with multiplier
            100 means 100 shares. No stock fees, funding or dividends modeled.

    Returns:
        Matrix shaped ``(len(iv_values), len(spot_grid))``.

    Raises:
        ValueError: If a leg, grid, market input, or cost input is invalid.
    """
    if not np.isfinite(underlying_qty):
        raise ValueError("underlying_qty must be finite")
    _validate_legs(legs)
    _validate_market_inputs(
        entry_spot=entry_spot,
        time_to_expiry=time_to_expiry,
        rate=rate,
        iv=entry_iv,
        multiplier=multiplier,
        commission_rate=commission_rate,
    )
    spots = _validate_grid(spot_grid, name="spot_grid", allow_zero=True)
    ivs = _validate_grid(iv_values, name="iv_values", allow_zero=False)
    entry_premiums = _leg_premiums(legs, entry_spot, time_to_expiry, rate, entry_iv)
    _, _, entry_cost = _entry_costs(legs, entry_premiums, multiplier, commission_rate)

    grid = np.zeros((len(ivs), len(spots)), dtype=float)
    for iv_row, iv_now in enumerate(ivs):
        for spot_col, spot_now in enumerate(spots):
            marked_value = 0.0
            for leg in legs:
                marked_value += (
                    leg.qty
                    * bs_price(
                        float(spot_now),
                        leg.strike,
                        time_to_expiry,
                        rate,
                        float(iv_now),
                        leg.option_type,
                    )
                    * multiplier
                )
            grid[iv_row, spot_col] = marked_value - entry_cost + underlying_qty * multiplier * (spot_now - entry_spot)
    return grid


def bull_call_spread(lower_strike: float, upper_strike: float, qty: int = 1) -> list[OptionLeg]:
    """Build a long lower-strike/short upper-strike call spread."""
    if upper_strike <= lower_strike:
        raise ValueError("upper strike must sit above lower strike")
    if isinstance(qty, bool) or not isinstance(qty, (int, np.integer)) or qty <= 0:
        raise ValueError("qty must be positive")
    return [
        OptionLeg("call", lower_strike, qty),
        OptionLeg("call", upper_strike, -qty),
    ]


def long_straddle(strike: float, qty: int = 1) -> list[OptionLeg]:
    """Build a long call plus long put at the same strike."""
    if isinstance(qty, bool) or not isinstance(qty, (int, np.integer)) or qty <= 0:
        raise ValueError("qty must be positive")
    return [OptionLeg("call", strike, qty), OptionLeg("put", strike, qty)]


def iron_condor(
    put_wing: float,
    put_body: float,
    call_body: float,
    call_wing: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """Build a defined-risk short iron condor."""
    if not (put_wing < put_body < call_body < call_wing):
        raise ValueError("strikes must nest as put_wing < put_body < call_body < call_wing")
    if isinstance(qty, bool) or not isinstance(qty, (int, np.integer)) or qty <= 0:
        raise ValueError("qty must be positive")
    return [
        OptionLeg("put", put_wing, qty),
        OptionLeg("put", put_body, -qty),
        OptionLeg("call", call_body, -qty),
        OptionLeg("call", call_wing, qty),
    ]
