"""Heston (1993) stochastic volatility option pricing model.

Implements semi-analytical European option pricing under the Heston model
via numerical quadrature of the characteristic function (Lewis 2001 / Albrecher et al. 2007 formulation).

Model dynamics:
    dS_t = (r - q) * S_t * dt + sqrt(V_t) * S_t * dW_1,t
    dV_t = kappa * (theta - V_t) * dt + sigma_v * sqrt(V_t) * dW_2,t
    d<W_1, W_2>_t = rho * dt

Parameters:
    S0: Initial spot price (> 0)
    K: Strike price (> 0)
    T: Time to expiration in years (> 0)
    r: Continuously compounded risk-free rate
    q: Continuously compounded dividend yield
    v0: Initial variance (> 0)
    kappa: Mean-reversion rate (> 0)
    theta: Long-term variance (> 0)
    sigma_v: Volatility of variance (> 0)
    rho: Correlation between spot and variance Brownian motions in [-1, 1]
"""

from __future__ import annotations

import cmath
import math
from collections.abc import Mapping, Sequence
from numbers import Real

from scipy.integrate import quad
from src.quantlib.options import _no_arbitrage_bounds, bs_price, normalise_option_type

__all__ = [
    "heston_characteristic_function",
    "heston_price",
    "heston_feller_condition",
    "implied_volatility_surface",
    "diagnose_iv_surface",
]


#: Point at which ``heston_price`` splits its integral into a finite part and
#: an infinite tail when no ``integration_limit`` is given.
_HESTON_SPLIT = 200.0


def heston_feller_condition(
    kappa: float, theta: float, sigma_v: float
) -> dict[str, float | bool]:
    """Check Feller condition (2 * kappa * theta > sigma_v**2).

    When satisfied, variance process V_t strictly stays positive (never reaches zero).

    Args:
        kappa: Mean reversion rate.
        theta: Long-term variance.
        sigma_v: Volatility of variance.

    Returns:
        dict with keys:
            * ``feller_ratio`` (float): 2 * kappa * theta / (sigma_v**2)
            * ``is_satisfied`` (bool): True if feller_ratio > 1.0.
    """
    for name, value in (("kappa", kappa), ("theta", theta), ("sigma_v", sigma_v)):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value}")
    if sigma_v <= 0.0:
        raise ValueError(f"sigma_v must be strictly positive, got {sigma_v}")
    if kappa <= 0.0 or theta <= 0.0:
        raise ValueError(
            f"kappa and theta must be strictly positive, got kappa={kappa}, theta={theta}"
        )

    ratio = float((2.0 * kappa * theta) / (sigma_v**2))
    return {
        "feller_ratio": ratio,
        "is_satisfied": bool(ratio > 1.0),
    }


def heston_characteristic_function(
    u: complex | float,
    S0: float,
    T: float,
    r: float,
    q: float,
    v0: float,
    kappa: float,
    theta: float,
    sigma_v: float,
    rho: float,
) -> complex:
    """Evaluate the Heston characteristic function phi(u) for log(S_T).

    Uses the Albrecher et al. (2007) formulation (Little Heston Trap stable branch).
    """
    i = 1j
    x0 = math.log(S0)
    sigma_sq = sigma_v**2

    # Continuous branch under risk-neutral measure
    term = kappa - i * rho * sigma_v * u
    d = cmath.sqrt(term**2 + sigma_sq * (i * u + u**2))
    g = (term - d) / (term + d)

    exp_neg_dt = cmath.exp(-d * T)
    one_minus_g_exp = 1.0 - g * exp_neg_dt
    one_minus_g = 1.0 - g

    C = (r - q) * i * u * T + (kappa * theta / sigma_sq) * (
        (term - d) * T - 2.0 * cmath.log(one_minus_g_exp / one_minus_g)
    )
    D = ((term - d) / sigma_sq) * ((1.0 - exp_neg_dt) / one_minus_g_exp)

    return cmath.exp(C + D * v0 + i * u * x0)


def heston_price(
    S0: float,
    K: float,
    T: float,
    r: float,
    v0: float,
    kappa: float,
    theta: float,
    sigma_v: float,
    rho: float,
    option_type: str = "call",
    q: float = 0.0,
    integration_limit: float | None = None,
) -> float:
    """Price a European option under the Heston stochastic volatility model.

    Uses Lewis (2001) / Carr-Madan single-integral formulation with stable characteristic function.

    Args:
        S0: Current spot price (> 0).
        K: Strike price (> 0).
        T: Time to expiry in years (> 0).
        r: Risk-free rate.
        v0: Initial variance (> 0).
        kappa: Mean reversion speed (> 0).
        theta: Long-term variance (> 0).
        sigma_v: Volatility of variance (> 0).
        rho: Spot-variance correlation in [-1.0, 1.0].
        option_type: 'call' or 'put'.
        q: Continuous dividend yield.
        integration_limit: Upper limit for numerical quadrature. The default,
            None, integrates to infinity. A finite limit truncates the integral,
            which is only accurate when the integrand has decayed by then: for an
            option a day or less from expiry it has not decayed by ``u = 200``,
            and the truncated price can be off by more than 10%.

    Returns:
        Option price as a non-negative float.
    """
    for name, value in (
        ("S0", S0),
        ("K", K),
        ("T", T),
        ("r", r),
        ("q", q),
        ("v0", v0),
        ("kappa", kappa),
        ("theta", theta),
        ("sigma_v", sigma_v),
        ("rho", rho),
        ("integration_limit", 1.0 if integration_limit is None else integration_limit),
    ):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value}")
    if integration_limit is not None and integration_limit <= 0.0:
        raise ValueError("integration_limit must be strictly positive")
    if S0 <= 0.0 or K <= 0.0:
        raise ValueError(f"Spot S0 and strike K must be positive, got S0={S0}, K={K}")
    if T <= 0.0:
        opt_type = normalise_option_type(option_type)
        return float(max(0.0, S0 - K) if opt_type == "call" else max(0.0, K - S0))
    if v0 < 0.0 or kappa <= 0.0 or theta <= 0.0 or sigma_v <= 0.0:
        raise ValueError(
            "v0 must be >= 0, and kappa, theta, sigma_v must be strictly positive"
        )
    if not (-1.0 <= rho <= 1.0):
        raise ValueError(f"rho must be in [-1.0, 1.0], got {rho}")

    opt_type = normalise_option_type(option_type)
    k = math.log(S0 / K) + (r - q) * T

    def integrand(u: float) -> float:
        if u == 0.0:
            return 0.0
        # The sign of this exponent is load-bearing and invisible to the usual
        # sanity checks. With sigma_v -> 0 the centered CF is real, so
        # Re[e^{+iuk} phi] == Re[e^{-iuk} phi] and the Black-Scholes limit
        # passes either way; at-the-money k is 0, so benchmark and put-call
        # parity checks pass either way too. It only shows up once rho != 0,
        # where flipping it inverts the volatility skew — a negative rho would
        # price OTM calls richer than ITM ones. test_volatility pins the skew
        # direction for exactly this reason.
        # Centered characteristic function for u - i/2
        phi = heston_characteristic_function(
            u=u - 0.5j,
            S0=1.0,
            T=T,
            r=0.0,
            q=0.0,
            v0=v0,
            kappa=kappa,
            theta=theta,
            sigma_v=sigma_v,
            rho=rho,
        )
        val = cmath.exp(1j * u * k) * phi / (u**2 + 0.25)
        return float(val.real)

    if integration_limit is None:
        # The integrand decays like the characteristic function, whose width in
        # u grows as 1/sqrt(v*T), so no fixed upper limit is accurate for every
        # expiry. Integrate the bulk on a finite interval and add the tail.
        integ, _ = quad(integrand, 0.0, _HESTON_SPLIT, limit=2000)
        tail, _ = quad(integrand, _HESTON_SPLIT, math.inf, limit=2000)
        integ += tail
    else:
        integ, _ = quad(integrand, 0.0, integration_limit, limit=2000)
    prefactor = (1.0 / math.pi) * math.sqrt(S0 * K) * math.exp(-0.5 * (r + q) * T)
    call = float(S0 * math.exp(-q * T) - prefactor * integ)
    call = float(max(0.0, call))

    if opt_type == "call":
        return call
    else:
        discounted_F = S0 * math.exp(-q * T)
        discounted_K = K * math.exp(-r * T)
        put = call - discounted_F + discounted_K
        return float(max(0.0, put))


_SURFACE_GRID_LIMIT = 400
_SURFACE_FIELDS = {"strike", "time_to_expiry", "implied_volatility"}


def _surface_number(value: Real, name: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number, got {value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if result < 0.0 or (result == 0.0 and not allow_zero):
        relation = "non-negative" if allow_zero else "strictly positive"
        raise ValueError(f"{name} must be {relation}, got {value!r}")
    return result


def _surface_grid(
    values: Sequence[Real] | None, defaults: Sequence[float], name: str
) -> list[float]:
    if values is None:
        return list(defaults)
    try:
        supplied = list(values)
    except TypeError as exc:
        raise ValueError(f"{name} grid must be a sequence of real numbers") from exc
    if not supplied:
        raise ValueError(f"{name} grid must not be empty")
    return sorted({_surface_number(value, f"{name} grid value") for value in supplied})


def _surface_log_ratio(upper: float, lower: float) -> float:
    """Compute log(upper / lower) for ordered positive strikes without overflow."""
    relative_gap = (upper - lower) / lower
    if math.isfinite(relative_gap):
        # Unlike subtracting two logs, log1p preserves adjacent float strikes.
        return math.log1p(relative_gap)
    return math.log(upper) - math.log(lower)


def _surface_variance(iv: float, expiry: float) -> float:
    """Compute total variance, refusing overflow or loss of a positive value."""
    # Squaring IV first can overflow/underflow even when IV**2 * T fits.
    scaled = iv * math.sqrt(expiry)
    variance = scaled * scaled
    if not math.isfinite(variance) or (iv > 0.0 and variance == 0.0):
        raise ValueError(
            "total variance is outside the representable floating-point range"
        )
    return variance


def _surface_observations(
    observations: Sequence[Mapping[str, Real]],
) -> tuple[dict[float, list[tuple[float, float]]], set[tuple[float, float]]]:
    if not observations:
        raise ValueError("at least one volatility observation is required")
    groups: dict[float, list[tuple[float, float]]] = {}
    seen: set[tuple[float, float]] = set()
    for index, observation in enumerate(observations):
        if not isinstance(observation, Mapping) or set(observation) != _SURFACE_FIELDS:
            raise ValueError(
                "each observation must contain exactly strike, time_to_expiry "
                f"and implied_volatility; invalid index {index}"
            )
        strike = _surface_number(observation["strike"], f"observation {index} strike")
        expiry = _surface_number(
            observation["time_to_expiry"], f"observation {index} time_to_expiry"
        )
        iv = _surface_number(
            observation["implied_volatility"],
            f"observation {index} implied_volatility",
            allow_zero=True,
        )
        key = (expiry, strike)
        if key in seen:
            raise ValueError(f"duplicate expiry/strike observation: {key}")
        seen.add(key)
        groups.setdefault(expiry, []).append((strike, iv))
    for expiry in groups:
        groups[expiry].sort()
    return groups, seen


def implied_volatility_surface(
    observations: Sequence[Mapping[str, Real]],
    *,
    spot: Real,
    strikes: Sequence[Real] | None = None,
    expiries: Sequence[Real] | None = None,
) -> dict[str, object]:
    """Build a bounded strike-by-expiry grid from observed implied volatilities.

    This is a display and exploratory-analysis grid, not an arbitrage-free
    pricing model. Within each observed expiry, IV is interpolated linearly in
    log-moneyness. Between two adjacent expiries, total variance is interpolated
    linearly before converting back to IV at the requested expiry. Requests
    outside the convex coverage of those slices are rejected instead of being
    silently extrapolated.

    Args:
        observations: Mappings with exactly ``strike``, ``time_to_expiry`` (in
            years) and ``implied_volatility`` (decimal, so 0.20 means 20%). Each
            expiry/strike pair must be unique. Values must be finite and
            positive, except that zero IV is accepted.
        spot: Positive underlying spot used for log-moneyness coordinates.
        strikes: Optional strike grid. Defaults to every observed strike.
        expiries: Optional expiry grid in years. Defaults to observed expiries.

    Returns:
        A deterministic dictionary with the normalized grids, interpolation
        contract, and one record per grid point. Each point contains ``strike``,
        ``time_to_expiry``, ``implied_volatility``, ``total_variance`` and
        ``source`` (``observed`` or ``interpolated``). The cross product is
        limited to 400 points so callers can render or serialize it directly.

    Raises:
        ValueError: If observations are empty, malformed, duplicated, or a grid
            point would require extrapolation beyond adjacent quote coverage,
            or its total variance cannot be represented as a finite float
            without rounding a positive value to zero.
    """
    _surface_number(spot, "spot")
    groups, seen = _surface_observations(observations)
    observed_expiries = sorted(groups)
    observed_strikes = sorted(
        {strike for values in groups.values() for strike, _ in values}
    )
    strike_grid = _surface_grid(strikes, observed_strikes, "strikes")
    expiry_grid = _surface_grid(expiries, observed_expiries, "expiries")
    if len(strike_grid) * len(expiry_grid) > _SURFACE_GRID_LIMIT:
        raise ValueError(
            f"grid exceeds {_SURFACE_GRID_LIMIT} points; narrow strikes or expiries"
        )

    def smile(expiry: float, strike: float) -> float:
        quotes = groups[expiry]
        lower = quotes[0][0]
        upper = quotes[-1][0]
        if strike < lower or strike > upper:
            raise ValueError(
                f"no extrapolation: strike {strike} is outside [{lower}, {upper}] for expiry {expiry}"
            )
        for (left_strike, left_iv), (right_strike, right_iv) in zip(quotes, quotes[1:]):
            if left_strike <= strike <= right_strike:
                if strike == left_strike:
                    return left_iv
                if strike == right_strike:
                    return right_iv
                # The spot cancels from log-moneyness differences. Avoid
                # forming strike / spot, which may overflow or round to zero.
                weight = _surface_log_ratio(strike, left_strike) / _surface_log_ratio(
                    right_strike, left_strike
                )
                return (1.0 - weight) * left_iv + weight * right_iv
        return quotes[0][1]

    points: list[dict[str, object]] = []
    for expiry in expiry_grid:
        if expiry < observed_expiries[0] or expiry > observed_expiries[-1]:
            raise ValueError(
                f"no extrapolation: expiry {expiry} is outside [{observed_expiries[0]}, {observed_expiries[-1]}]"
            )
        for strike in strike_grid:
            if expiry in groups:
                iv = smile(expiry, strike)
                total_variance = _surface_variance(iv, expiry)
            else:
                next_expiry = next(
                    value for value in observed_expiries if value > expiry
                )
                previous_expiry = observed_expiries[
                    observed_expiries.index(next_expiry) - 1
                ]
                lower_iv = smile(previous_expiry, strike)
                upper_iv = smile(next_expiry, strike)
                lower_variance = _surface_variance(lower_iv, previous_expiry)
                upper_variance = _surface_variance(upper_iv, next_expiry)
                weight = (expiry - previous_expiry) / (next_expiry - previous_expiry)
                total_variance = (
                    1.0 - weight
                ) * lower_variance + weight * upper_variance
                if total_variance == 0.0 and (
                    lower_variance > 0.0 or upper_variance > 0.0
                ):
                    raise ValueError(
                        "interpolated total variance is below the representable floating-point range"
                    )
                # The ratio can overflow even when its square root fits.
                iv = math.sqrt(total_variance) / math.sqrt(expiry)
            if not math.isfinite(iv) or not math.isfinite(total_variance):
                raise ValueError(
                    "interpolated IV or total variance is outside the representable floating-point range"
                )
            points.append(
                {
                    "strike": strike,
                    "time_to_expiry": expiry,
                    "implied_volatility": iv,
                    "total_variance": total_variance,
                    "source": (
                        "observed" if (expiry, strike) in seen else "interpolated"
                    ),
                }
            )

    return {
        "strikes": strike_grid,
        "expiries": expiry_grid,
        "interpolation": {
            "strike": "linear_iv_log_moneyness",
            "expiry": "linear_total_variance",
            "extrapolation": "rejected",
        },
        "points": points,
    }


_SURFACE_PRICE_RTOL = 1e-9
_SURFACE_FINDING_LIMIT = 20


def _surface_rate(value: Real, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite real number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite real number")
    return number


def diagnose_iv_surface(
    observations: Sequence[Mapping[str, Real]],
    *,
    spot: Real,
    risk_free_rate: Real = 0.0,
    dividend_yield: Real = 0.0,
) -> dict[str, object]:
    """Check observed IV slices against European call-price inequalities.

    Prices are reconstructed by the shared BSM function, not observed trade
    prices. Checks cover adjacent vertical spreads and three-strike convexity
    within each observed expiry only. They neither repair the display grid nor
    certify it as arbitrage-free; calendar spreads and trading frictions are
    outside this diagnostic.

    Args:
        observations: The same strike/expiry/decimal-IV mappings as the grid
            builder, with at most 400 observations.
        spot: Positive underlying spot, in the same units as strikes.
        risk_free_rate: Finite continuously compounded annual rate.
        dividend_yield: Finite continuously compounded annual dividend yield.

    Returns:
        Strict-JSON-safe coverage, per-slice availability and up to 20 findings.
        Comparison tolerance is relative to discounted spot with an eight-ULP
        floor. All finding counts remain complete when displayed rows are capped.

    Raises:
        ValueError: If observations or model parameters are invalid.
    """
    spot_value = _surface_number(spot, "spot")
    rate = _surface_rate(risk_free_rate, "risk_free_rate")
    dividend = _surface_rate(dividend_yield, "dividend_yield")
    if len(observations) > _SURFACE_GRID_LIMIT:
        raise ValueError(
            f"diagnostics accept at most {_SURFACE_GRID_LIMIT} observations"
        )
    groups, _ = _surface_observations(observations)
    checked = {"vertical_spreads": 0, "butterflies": 0}
    slices: list[dict[str, object]] = []
    findings: list[dict[str, object]] = []
    for expiry, quotes in sorted(groups.items()):
        summary: dict[str, object] = {
            "time_to_expiry": expiry,
            "observations": len(quotes),
            "status": "insufficient_points",
            "reason": None,
            "tolerance": None,
            "vertical_spreads": 0,
            "butterflies": 0,
        }
        slices.append(summary)
        if len(quotes) < 2:
            continue
        try:
            discount = math.exp(-rate * expiry)
            spot_pv = spot_value * math.exp(-dividend * expiry)
            tolerance = max(_SURFACE_PRICE_RTOL * spot_pv, 8.0 * math.ulp(spot_pv))
            if not (
                math.isfinite(discount)
                and discount > 0.0
                and math.isfinite(spot_pv)
                and spot_pv > tolerance
            ):
                raise ValueError("model price resolution is unavailable")
            for _, iv in quotes:
                _surface_variance(iv, expiry)
            prices = [
                bs_price(spot_value, strike, expiry, rate, iv, "call", dividend)
                for strike, iv in quotes
            ]
            bounds = [
                discount * (right[0] - left[0])
                for left, right in zip(quotes, quotes[1:])
            ]
            if not all(math.isfinite(value) for value in prices + bounds):
                raise ValueError("model prices exceed floating-point range")
            for (strike, _), price in zip(quotes, prices):
                lower, upper = _no_arbitrage_bounds(
                    spot_value, strike, expiry, rate, "call", dividend
                )
                if (
                    not (math.isfinite(lower) and math.isfinite(upper))
                    or price < lower - tolerance
                    or price > upper + tolerance
                ):
                    raise ValueError("model price is outside European call bounds")
            checks: list[tuple[str, list[float], float, float | None]] = []
            for index, upper in enumerate(bounds):
                checks.append(
                    (
                        "vertical_spread_bounds",
                        [quotes[index][0], quotes[index + 1][0]],
                        prices[index] - prices[index + 1],
                        upper,
                    )
                )
            for index in range(1, len(quotes) - 1):
                left, middle, right = [
                    quotes[i][0] for i in (index - 1, index, index + 1)
                ]
                weight = (middle - left) / (right - left)
                value = (
                    (1.0 - weight) * prices[index - 1]
                    + weight * prices[index + 1]
                    - prices[index]
                )
                checks.append(
                    ("butterfly_convexity", [left, middle, right], value, None)
                )
            if not all(math.isfinite(check[2]) for check in checks):
                raise ValueError("model price differences exceed floating-point range")
        except (OverflowError, ValueError, ZeroDivisionError):
            summary.update(status="unavailable", reason="model_price_out_of_range")
            continue

        summary.update(
            status="checked",
            tolerance=tolerance,
            vertical_spreads=len(quotes) - 1,
            butterflies=max(0, len(quotes) - 2),
        )
        checked["vertical_spreads"] += len(quotes) - 1
        checked["butterflies"] += max(0, len(quotes) - 2)
        for kind, strikes, value, upper in checks:
            if value < -tolerance or (upper is not None and value > upper + tolerance):
                findings.append(
                    {
                        "kind": kind,
                        "time_to_expiry": expiry,
                        "strikes": strikes,
                        "value": value,
                        "lower_bound": 0.0,
                        "upper_bound": upper,
                        "tolerance": tolerance,
                    }
                )
    return {
        "basis": "european_bsm_calls",
        "scope": "observed_strikes_per_expiry",
        "parameters": {
            "spot": spot_value,
            "risk_free_rate": rate,
            "dividend_yield": dividend,
            "relative_price_tolerance": _SURFACE_PRICE_RTOL,
        },
        "checked": checked,
        "slices": slices,
        "total_findings": len(findings),
        "limit": _SURFACE_FINDING_LIMIT,
        "findings": findings[:_SURFACE_FINDING_LIMIT],
    }
