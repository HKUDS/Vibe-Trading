"""Black-Scholes pricing, Greeks and implied-volatility inversion.

One implementation, called by both the backtest engine and the
``options-payoff`` skill. It merges two copies that had drifted apart: the
engine's (``backtest/engines/options_portfolio.py``, no dividend yield, no rho,
but with correct degenerate-input handling) and the skill's markdown listing
(dividend yield and rho, but it crashed on a non-positive spot/strike and
reported a zero delta for an expiring in-the-money option).

Conventions, fixed here so callers never have to guess:
  * ``T`` is in years, ``r`` and ``q`` are continuously compounded annual rates.
  * ``theta`` is per calendar day, ``vega`` and ``rho`` are per 1 percentage
    point of volatility / rate. ``delta`` and ``gamma`` are per 1.0 of spot.
  * Nothing is rounded. Rounding is a presentation decision and it destroys the
    vega precision the implied-volatility solver needs.

Degenerate inputs collapse the lognormal to a point mass. At expiry, or for a
non-positive spot/strike, the price is the immediate intrinsic value. With time
remaining but ``sigma <= 0``, the terminal spot is deterministic instead, so
the price is the discounted forward intrinsic value. They return that rather
than raising, because an expiring or zero-volatility leg is a normal state for a
backtest to walk through.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

__all__ = [
    "BARRIER_TYPES",
    "barrier_greeks",
    "barrier_option_price",
    "bs_greeks",
    "bs_price",
    "implied_volatility",
    "normalise_barrier_type",
    "normalise_option_type",
]

#: Widest volatility the implied-vol search will consider (1000% annualised).
#: Anything solving above this is an outlier or a bad print, not a vol.
MAX_SIGMA = 10.0
#: Narrowest volatility the search will consider; the bisection lower bracket.
MIN_SIGMA = 1e-6
#: Below this vega, Newton's step is numerically meaningless and the solver
#: hands over to bisection (deep in- or out-of-the-money, or near expiry).
MIN_VEGA = 1e-10
#: Brenner-Subrahmanyam seed is only valid near the money; clamp it before use.
MAX_SEED_SIGMA = 5.0
MIN_SEED_SIGMA = 1e-3
#: One volatility point. A solved vol is only reported when moving sigma by this
#: much moves the price by more than the solve tolerance -- otherwise a whole
#: band of volatilities fits the quote equally well and the "solution" is
#: whichever endpoint the search wandered to.
SIGMA_RESOLUTION = 0.01

_CALL = "call"
_PUT = "put"


#: Spellings folded to ``"call"``. Beyond case and padding these are the forms
#: real configs and real chain feeds actually carry: the single letter used in
#: option symbols and most vendor chains, the plural a chain endpoint returns,
#: and the two Chinese terms -- ``认购``/``认沽`` being the official SSE/SZSE
#: wording for exchange-traded options, which an A-share config will use.
_CALL_ALIASES: frozenset[str] = frozenset({"call", "calls", "c", "看涨", "认购"})

#: Spellings folded to ``"put"``. See :data:`_CALL_ALIASES`.
_PUT_ALIASES: frozenset[str] = frozenset({"put", "puts", "p", "看跌", "认沽"})


#: Standard barrier types
BARRIER_TYPES: tuple[str, ...] = (
    "down-and-out",
    "down-and-in",
    "up-and-out",
    "up-and-in",
)

_BARRIER_ALIASES: dict[str, str] = {
    "down-and-out": "down-and-out",
    "down_and_out": "down-and-out",
    "down and out": "down-and-out",
    "do": "down-and-out",
    "doc": "down-and-out",
    "dop": "down-and-out",
    "down-and-in": "down-and-in",
    "down_and_in": "down-and-in",
    "down and in": "down-and-in",
    "di": "down-and-in",
    "dic": "down-and-in",
    "dip": "down-and-in",
    "up-and-out": "up-and-out",
    "up_and_out": "up-and-out",
    "up and out": "up-and-out",
    "uo": "up-and-out",
    "uoc": "up-and-out",
    "uop": "up-and-out",
    "up-and-in": "up-and-in",
    "up_and_in": "up-and-in",
    "up and in": "up-and-in",
    "ui": "up-and-in",
    "uic": "up-and-in",
    "uip": "up-and-in",
}


def normalise_barrier_type(barrier_type: str) -> str:
    """Fold a barrier-type string to one of :data:`BARRIER_TYPES`."""
    cleaned = barrier_type.strip().lower()
    if cleaned in _BARRIER_ALIASES:
        return _BARRIER_ALIASES[cleaned]
    raise ValueError(
        f"unknown barrier type {barrier_type!r}; valid types: {BARRIER_TYPES}"
    )


def normalise_option_type(option_type: str) -> str:
    """Fold an option-type string to ``"call"`` or ``"put"``.

    Public because callers that *store* an option type must fold it with the
    same rule the pricing functions use. Anything that keeps the raw string and
    later compares it with ``== "call"`` will price a leg typed ``"Call"`` as a
    call here and settle it as a put there.

    WHY THIS ACCEPTS ALIASES BUT STILL REFUSES THE UNKNOWN
    -----------------------------------------------------
    There are two different failure modes and they need opposite treatment.

    A config saying ``"C"``, ``"calls"`` or ``"认购"`` is *unambiguous* -- there
    is exactly one thing it can mean, and refusing it breaks a working setup for
    no safety gain. Those are folded (:data:`_CALL_ALIASES`, :data:`_PUT_ALIASES`).

    A config saying ``"cal"`` or ``"kall"`` is a typo, and the only safe answer
    is to stop. The behaviour this replaced defaulted an unrecognised type to
    put, so a mistyped call leg opened priced as a call and settled as a put --
    ten in-the-money contracts settling at zero. Guessing at a typo is how that
    happened, so an unknown string still raises.

    Args:
        option_type: Caller-supplied option type. Case, surrounding whitespace
            and the aliases above are all accepted.

    Returns:
        Either ``"call"`` or ``"put"``.

    Raises:
        ValueError: If the string matches no known spelling. The message lists
            what is accepted, so the fix does not need a source read.
    """
    folded = str(option_type).strip().lower()
    if folded in _CALL_ALIASES:
        return _CALL
    if folded in _PUT_ALIASES:
        return _PUT
    raise ValueError(
        f"unrecognised option_type {option_type!r}. Accepted (any case): "
        f"{sorted(_CALL_ALIASES)} for a call, {sorted(_PUT_ALIASES)} for a put. "
        "An unrecognised type is not defaulted, because defaulting one is how a "
        "call leg gets settled as a put."
    )


def _intrinsic(S: float, K: float, option_type: str) -> float:
    """Undiscounted exercise value of an option.

    Args:
        S: Underlying spot price.
        K: Strike price.
        option_type: Normalised ``"call"`` or ``"put"``.

    Returns:
        ``max(S - K, 0)`` for a call, ``max(K - S, 0)`` for a put. Always a
        float, even for integer inputs, so the public annotations hold.
    """
    return float(max(S - K, 0.0) if option_type == _CALL else max(K - S, 0.0))


def _uses_immediate_intrinsic(S: float, K: float, T: float) -> bool:
    """Report whether pricing must use immediate intrinsic value.

    Args:
        S: Underlying spot price.
        K: Strike price.
        T: Time to expiry in years.
    Returns:
        True at/past expiry or when spot/strike makes lognormal pricing
        undefined.
    """
    return T <= 0 or S <= 0 or K <= 0


def _discounted_forward_values(S: float, K: float, T: float, r: float,
                               q: float) -> tuple[float, float]:
    """Return discounted spot and strike values for deterministic pricing."""
    return float(S * np.exp(-q * T)), float(K * np.exp(-r * T))


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float,
           q: float) -> tuple[float, float]:
    """Compute the Black-Scholes d1 and d2 terms.

    Args:
        S: Underlying spot price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free rate, continuously compounded.
        sigma: Annualised volatility.
        q: Continuous dividend yield.

    Returns:
        The pair ``(d1, d2)``.
    """
    sqrt_T = np.sqrt(T)
    d1 = (np.log(S / K) + (r - q + sigma ** 2 / 2) * T) / (sigma * sqrt_T)
    return float(d1), float(d1 - sigma * sqrt_T)


def bs_price(S: float, K: float, T: float, r: float, sigma: float,
             option_type: str = "call", q: float = 0.0) -> float:
    """Price a European option with the Black-Scholes-Merton formula.

    Args:
        S: Underlying spot price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free rate, continuously compounded and annualised.
        sigma: Annualised volatility.
        option_type: ``"call"`` or ``"put"``, case-insensitive.
        q: Continuous dividend yield, annualised. Defaults to 0.

    Returns:
        Theoretical option price. Expired inputs return immediate intrinsic
        value; non-positive volatility with time remaining returns discounted
        forward intrinsic value.

    Raises:
        ValueError: If ``option_type`` is neither call nor put.

    Example:
        >>> round(bs_price(100, 100, 1.0, 0.05, 0.2, "call"), 2)
        10.45
    """
    option_type = normalise_option_type(option_type)
    if _uses_immediate_intrinsic(S, K, T):
        return _intrinsic(S, K, option_type)
    if sigma <= 0:
        spot_pv, strike_pv = _discounted_forward_values(S, K, T, r, q)
        return float(
            max(spot_pv - strike_pv, 0.0)
            if option_type == _CALL
            else max(strike_pv - spot_pv, 0.0)
        )

    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    spot_pv = S * np.exp(-q * T)
    strike_pv = K * np.exp(-r * T)

    if option_type == _CALL:
        return float(spot_pv * norm.cdf(d1) - strike_pv * norm.cdf(d2))
    return float(strike_pv * norm.cdf(-d2) - spot_pv * norm.cdf(-d1))


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float,
              option_type: str = "call", q: float = 0.0) -> Dict[str, float]:
    """Compute the five Black-Scholes-Merton Greeks.

    Args:
        S: Underlying spot price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free rate, continuously compounded and annualised.
        sigma: Annualised volatility.
        option_type: ``"call"`` or ``"put"``, case-insensitive.
        q: Continuous dividend yield, annualised. Defaults to 0.

    Returns:
        Dict with ``delta``, ``gamma``, ``theta``, ``vega`` and ``rho``.
        ``theta`` is per calendar day; ``vega`` and ``rho`` are per 1 percentage
        point. Expired inputs return immediate-intrinsic Greeks. Non-positive
        volatility with time remaining returns the first-order sensitivities of
        discounted forward intrinsic value, with gamma and vega zero.

    Raises:
        ValueError: If ``option_type`` is neither call nor put.
    """
    option_type = normalise_option_type(option_type)
    if _uses_immediate_intrinsic(S, K, T):
        # An expiring in-the-money option still has unit exposure to spot, so
        # delta must not be reported as zero here. At S == K the one-sided
        # limits disagree (1 from above, 0 from below for a call), so take the
        # midpoint: any other choice breaks call_delta - put_delta == 1 at
        # precisely one point and silently corrupts a hedge ratio there.
        if S == K:
            delta = 0.5 if option_type == _CALL else -0.5
        elif option_type == _CALL:
            delta = 1.0 if S > K else 0.0
        else:
            delta = -1.0 if S < K else 0.0
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    if sigma <= 0:
        spot_pv, strike_pv = _discounted_forward_values(S, K, T, r, q)
        forward_moneyness = spot_pv - strike_pv
        if forward_moneyness == 0:
            exercise_weight = 0.5
        elif option_type == _CALL:
            exercise_weight = 1.0 if forward_moneyness > 0 else 0.0
        else:
            exercise_weight = 1.0 if forward_moneyness < 0 else 0.0

        disc_q = float(np.exp(-q * T))
        rho_scale = K * T * float(np.exp(-r * T)) / 100.0
        carry = (q * spot_pv - r * strike_pv) / 365.0
        if option_type == _CALL:
            delta = exercise_weight * disc_q
            theta = exercise_weight * carry
            rho = exercise_weight * rho_scale
        else:
            delta = -exercise_weight * disc_q
            theta = -exercise_weight * carry
            rho = -exercise_weight * rho_scale
        return {
            "delta": float(delta),
            "gamma": 0.0,
            "theta": float(theta),
            "vega": 0.0,
            "rho": float(rho),
        }

    sqrt_T = float(np.sqrt(T))
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    pdf_d1 = float(norm.pdf(d1))
    disc_q = float(np.exp(-q * T))
    disc_r = float(np.exp(-r * T))

    carry_theta = -(S * disc_q * pdf_d1 * sigma) / (2 * sqrt_T)
    if option_type == _CALL:
        delta = disc_q * float(norm.cdf(d1))
        theta = (carry_theta
                 - r * K * disc_r * float(norm.cdf(d2))
                 + q * S * disc_q * float(norm.cdf(d1)))
        rho = K * T * disc_r * float(norm.cdf(d2)) / 100.0
    else:
        delta = disc_q * (float(norm.cdf(d1)) - 1.0)
        theta = (carry_theta
                 + r * K * disc_r * float(norm.cdf(-d2))
                 - q * S * disc_q * float(norm.cdf(-d1)))
        rho = -K * T * disc_r * float(norm.cdf(-d2)) / 100.0

    return {
        "delta": float(delta),
        "gamma": float(disc_q * pdf_d1 / (S * sigma * sqrt_T)),
        "theta": float(theta / 365.0),
        "vega": float(S * disc_q * pdf_d1 * sqrt_T / 100.0),
        "rho": float(rho),
    }


def _no_arbitrage_bounds(S: float, K: float, T: float, r: float,
                         option_type: str, q: float) -> tuple[float, float]:
    """Return the price interval Black-Scholes can actually reach.

    As ``sigma`` goes to zero the price converges to the discounted forward
    intrinsic, and as ``sigma`` grows without bound a call converges to
    ``S*exp(-qT)`` and a put to ``K*exp(-rT)``. A quoted price outside that open
    interval has no implied volatility at all.

    Using the *undiscounted* intrinsic as the lower bound instead is wrong in
    both directions: with ``r > 0`` it lets through call prices no volatility can
    produce, and it rejects deep in-the-money European puts, which legitimately
    trade below ``K - S``.

    Args:
        S: Underlying spot price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free rate, continuously compounded.
        option_type: Normalised ``"call"`` or ``"put"``.
        q: Continuous dividend yield.

    Returns:
        The pair ``(lower, upper)``.
    """
    spot_pv = S * np.exp(-q * T)
    strike_pv = K * np.exp(-r * T)
    if option_type == _CALL:
        return max(spot_pv - strike_pv, 0.0), float(spot_pv)
    return max(strike_pv - spot_pv, 0.0), float(strike_pv)


def implied_volatility(market_price: float, S: float, K: float, T: float,
                       r: float, option_type: str = "call", q: float = 0.0,
                       tol: float = 1e-6, max_iter: int = 200) -> float:
    """Invert Black-Scholes for volatility, Newton first then bisection.

    Seeds with the Brenner-Subrahmanyam at-the-money approximation
    ``sigma_0 = sqrt(2*pi/T) * price / S`` and iterates
    ``sigma -= (BS(sigma) - price) / vega``. Where vega collapses (deep in- or
    out-of-the-money, or close to expiry) Newton's step is meaningless, so the
    solver hands over to bracketed bisection on ``[MIN_SIGMA, MAX_SIGMA]``.

    Args:
        market_price: Observed option price, same units as ``S`` and ``K``.
        S: Underlying spot price.
        K: Strike price.
        T: Time to expiry in years; must be positive.
        r: Risk-free rate, continuously compounded and annualised.
        option_type: ``"call"`` or ``"put"``, case-insensitive.
        q: Continuous dividend yield, annualised. Defaults to 0.
        tol: Absolute price tolerance for convergence.
        max_iter: Maximum Newton iterations before falling back to bisection.

    Returns:
        Annualised implied volatility. ``nan`` if neither method converges
        inside ``[MIN_SIGMA, MAX_SIGMA]``, and also ``nan`` when the quote does
        not identify a volatility at all.

        The second case is the one worth understanding. Convergence is on
        *price*, so where the price is flat in ``sigma`` -- very deep in or out
        of the money, or right before expiry -- many volatilities satisfy
        ``tol`` and any of them would "converge". A 20-day call struck at half
        the spot prices identically to 16 decimal places for every ``sigma``
        from 0.05 to 0.60, so a solver that answers there is reporting the
        arbitrary endpoint of its own search, not a market volatility. This
        function refuses that: it checks vega at the candidate solution and
        returns ``nan`` when the price carries no volatility information. That
        is a property of the quote rather than a solver failure, and no
        price-tolerance method can do better -- but a confident wrong number is
        worse than an admitted absence.

    Raises:
        ValueError: If ``option_type`` is invalid, if ``T``, ``S`` or ``K`` is
            non-positive, or if ``market_price`` lies outside the no-arbitrage
            interval, which includes the intrinsic-value violation
            ``market_price < discounted intrinsic``.
    """
    option_type = normalise_option_type(option_type)
    if T <= 0:
        raise ValueError(f"T must be > 0 to imply a volatility, got {T}")
    if S <= 0 or K <= 0:
        raise ValueError(f"S and K must be > 0, got S={S}, K={K}")

    lower, upper = _no_arbitrage_bounds(S, K, T, r, option_type, q)
    if market_price < lower - tol:
        raise ValueError(
            f"market price {market_price} is below intrinsic value {lower}"
        )
    if market_price >= upper:
        raise ValueError(
            f"market price {market_price} is at or above the no-arbitrage "
            f"ceiling {upper}; no implied volatility exists"
        )

    def identified(candidate: float) -> float:
        """Return the candidate only if the quote actually pins it down.

        The test is whether one volatility point of movement shifts the price by
        more than the tolerance the solve was run to. If it does not, then a
        whole band of volatilities reprices within ``tol`` and whichever one the
        search happens to land on is an artefact of the search, not a reading of
        the market. Comparing vega against an absolute floor cannot express
        this, because the threshold has to scale with ``tol``.

        Args:
            candidate: A volatility that reprices to within ``tol``.

        Returns:
            ``candidate`` when the price responds to volatility there,
            otherwise ``nan``.
        """
        vega = bs_greeks(S, K, T, r, candidate, option_type, q)["vega"] * 100.0
        resolvable = abs(vega) * SIGMA_RESOLUTION >= tol
        return candidate if resolvable else float("nan")

    sigma = float(np.sqrt(2 * np.pi / T) * market_price / S)
    sigma = min(max(sigma, MIN_SEED_SIGMA), MAX_SEED_SIGMA)

    for _ in range(max_iter):
        diff = bs_price(S, K, T, r, sigma, option_type, q) - market_price
        if abs(diff) < tol:
            return identified(sigma)
        # bs_greeks reports vega per 1 percentage point; Newton needs per 1.0.
        vega = bs_greeks(S, K, T, r, sigma, option_type, q)["vega"] * 100.0
        if abs(vega) < MIN_VEGA:
            break
        sigma = min(max(sigma - diff / vega, MIN_SIGMA), MAX_SIGMA)

    try:
        return identified(float(brentq(
            lambda v: bs_price(S, K, T, r, v, option_type, q) - market_price,
            MIN_SIGMA, MAX_SIGMA, xtol=tol, maxiter=max_iter,
        )))
    except (ValueError, RuntimeError):
        # ValueError: the bracket does not straddle a root. RuntimeError: brentq
        # ran out of its own iterations. Both mean "no volatility found", and
        # the documented contract for that is nan, not an exception escaping
        # from a private implementation detail.
        return float("nan")


def barrier_option_price(
    S: float,
    K: float,
    H: float,
    T: float,
    r: float,
    sigma: float,
    barrier_type: str,
    option_type: str = "call",
    q: float = 0.0,
    rebate: float = 0.0,
) -> float:
    """Analytical Black-Scholes pricing for single-barrier options (Reiner-Rubinstein 1991).

    Supports all 8 standard barrier option combinations:
      * Down-and-out / Down-and-in (Call / Put)
      * Up-and-out / Up-and-in (Call / Put)

    with continuous monitoring, continuous dividend yield ``q``, and optional
    expiry cash rebate ``rebate``.

    Satisfies the exact In-Out parity identity:
        Price(Knock-In) + Price(Knock-Out) = Price(Vanilla) + rebate * exp(-r * T)

    Args:
        S: Current spot price, strictly positive.
        K: Strike price, strictly positive.
        H: Barrier price level, strictly positive.
        T: Time to expiration in years.
        r: Continuously compounded risk-free rate.
        sigma: Annualised volatility.
        barrier_type: One of :data:`BARRIER_TYPES` (or aliases e.g. ``'down-and-out'``, ``'ui'``).
        option_type: ``'call'`` or ``'put'``.
        q: Continuously compounded dividend yield.
        rebate: Fixed cash rebate paid at expiration if knocked out (or never knocked in).

    Returns:
        Option price as a non-negative float.

    Raises:
        ValueError: If S, K, or H <= 0, or barrier_type is unknown.
    """
    if S <= 0.0 or K <= 0.0 or H <= 0.0:
        raise ValueError(f"Spot, strike, and barrier must be strictly positive, got S={S}, K={K}, H={H}")

    b_type = normalise_barrier_type(barrier_type)
    opt_type = normalise_option_type(option_type)

    # Degenerate expiry or zero/negative volatility
    if T <= 0.0 or sigma <= 0.0:
        vanilla = bs_price(S, K, T, r, sigma, opt_type, q)
        rebate_pv = rebate * float(np.exp(-r * T))
        is_down = "down" in b_type
        if T > 0.0 and sigma <= 0.0:
            F = S * float(np.exp((r - q) * T))
            breached = (min(S, F) <= H) if is_down else (max(S, F) >= H)
        else:
            breached = (S <= H) if is_down else (S >= H)
        if "out" in b_type:
            return rebate_pv if breached else vanilla
        else:  # "in"
            return vanilla if breached else rebate_pv

    # Check initial boundary conditions
    is_down = "down" in b_type
    if is_down and S <= H:
        if "out" in b_type:
            return rebate * np.exp(-r * T)
        else:
            return bs_price(S, K, T, r, sigma, opt_type, q)
    elif (not is_down) and S >= H:
        if "out" in b_type:
            return rebate * np.exp(-r * T)
        else:
            return bs_price(S, K, T, r, sigma, opt_type, q)

    phi = 1.0 if opt_type == _CALL else -1.0
    eta = 1.0 if is_down else -1.0

    b = r - q
    sigma_sqrt_T = sigma * np.sqrt(T)
    mu = (b - 0.5 * sigma**2) / (sigma**2)

    x1 = np.log(S / K) / sigma_sqrt_T + (1.0 + mu) * sigma_sqrt_T
    x2 = np.log(S / H) / sigma_sqrt_T + (1.0 + mu) * sigma_sqrt_T
    y1 = np.log(H**2 / (S * K)) / sigma_sqrt_T + (1.0 + mu) * sigma_sqrt_T
    y2 = np.log(H / S) / sigma_sqrt_T + (1.0 + mu) * sigma_sqrt_T

    df_q = np.exp(-q * T)
    df_r = np.exp(-r * T)
    hs_ratio = H / S

    A = phi * S * df_q * norm.cdf(phi * x1) - phi * K * df_r * norm.cdf(phi * (x1 - sigma_sqrt_T))
    B = phi * S * df_q * norm.cdf(phi * x2) - phi * K * df_r * norm.cdf(phi * (x2 - sigma_sqrt_T))
    C = phi * S * df_q * (hs_ratio ** (2.0 * (mu + 1.0))) * norm.cdf(eta * y1) - phi * K * df_r * (
        hs_ratio ** (2.0 * mu)
    ) * norm.cdf(eta * (y1 - sigma_sqrt_T))
    D = phi * S * df_q * (hs_ratio ** (2.0 * (mu + 1.0))) * norm.cdf(eta * y2) - phi * K * df_r * (
        hs_ratio ** (2.0 * mu)
    ) * norm.cdf(eta * (y2 - sigma_sqrt_T))

    # Cash rebate component
    if rebate > 0.0:
        E = rebate * df_r * (norm.cdf(eta * (x2 - sigma_sqrt_T)) - (hs_ratio ** (2.0 * mu)) * norm.cdf(eta * (y2 - sigma_sqrt_T)))
    else:
        E = 0.0

    if opt_type == _CALL:
        if b_type == "down-and-out":
            price = (A - C + (rebate * df_r - E)) if K >= H else (B - D + (rebate * df_r - E))
        elif b_type == "down-and-in":
            price = (C + E) if K >= H else (A - B + D + E)
        elif b_type == "up-and-out":
            price = (rebate * df_r - E) if K >= H else (A - B + C - D + (rebate * df_r - E))
        elif b_type == "up-and-in":
            price = (A + E) if K >= H else (B - C + D + E)
        else:
            raise ValueError(f"Unhandled barrier type {b_type}")
    else:  # PUT
        if b_type == "down-and-out":
            price = (A - B + C - D + (rebate * df_r - E)) if K >= H else (rebate * df_r - E)
        elif b_type == "down-and-in":
            price = (B - C + D + E) if K >= H else (A + E)
        elif b_type == "up-and-out":
            price = (B - D + (rebate * df_r - E)) if K >= H else (A - C + (rebate * df_r - E))
        elif b_type == "up-and-in":
            price = (A - B + D + E) if K >= H else (C + E)
        else:
            raise ValueError(f"Unhandled barrier type {b_type}")

    return float(max(0.0, price))



def barrier_greeks(
    S: float,
    K: float,
    H: float,
    T: float,
    r: float,
    sigma: float,
    barrier_type: str,
    option_type: str = "call",
    q: float = 0.0,
    rebate: float = 0.0,
) -> dict[str, float]:
    """Compute sensitivity Greeks for single-barrier options via central finite differences.

    Matches the conventions of :func:`bs_greeks`:
      * delta: per 1.0 of spot
      * gamma: per 1.0 of spot squared
      * theta: per calendar day (1/365)
      * vega: per 1 percentage point of volatility (0.01)
      * rho: per 1 percentage point of interest rate (0.01)

    Args:
        S, K, H, T, r, sigma, barrier_type, option_type, q, rebate: Standard barrier inputs.

    Returns:
        dict with keys: ``delta``, ``gamma``, ``theta``, ``vega``, ``rho``.
    """
    p = barrier_option_price(S, K, H, T, r, sigma, barrier_type, option_type, q, rebate)

    dS = max(1e-4, 1e-4 * S)
    p_up = barrier_option_price(S + dS, K, H, T, r, sigma, barrier_type, option_type, q, rebate)
    p_down = barrier_option_price(S - dS, K, H, T, r, sigma, barrier_type, option_type, q, rebate)

    delta = float((p_up - p_down) / (2.0 * dS))
    gamma = float((p_up - 2.0 * p + p_down) / (dS**2))

    # Theta (per calendar day): time decay moves forward, so T - dt
    dt = 1.0 / 365.0
    if T > dt:
        p_dt = barrier_option_price(S, K, H, T - dt, r, sigma, barrier_type, option_type, q, rebate)
        theta = float(p_dt - p)
    else:
        theta = 0.0

    # Vega (per 1 percentage point = 0.01)
    dvol = 1e-4
    p_vol_up = barrier_option_price(S, K, H, T, r, sigma + dvol, barrier_type, option_type, q, rebate)
    p_vol_down = barrier_option_price(S, K, H, T, r, max(1e-6, sigma - dvol), barrier_type, option_type, q, rebate)
    vega = float((p_vol_up - p_vol_down) / (2.0 * dvol) * 0.01)

    # Rho (per 1 percentage point = 0.01)
    dr = 1e-4
    p_r_up = barrier_option_price(S, K, H, T, r + dr, sigma, barrier_type, option_type, q, rebate)
    p_r_down = barrier_option_price(S, K, H, T, r - dr, sigma, barrier_type, option_type, q, rebate)
    rho = float((p_r_up - p_r_down) / (2.0 * dr) * 0.01)

    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "rho": rho,
    }
