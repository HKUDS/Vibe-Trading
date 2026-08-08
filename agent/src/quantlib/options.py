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

Degenerate inputs (``T <= 0``, ``sigma <= 0``, ``S <= 0`` or ``K <= 0``) collapse
the lognormal to a point mass, so the price is the intrinsic value and every
second-order Greek is zero. They return that rather than raising, because an
expiring or zero-strike leg is a normal state for a backtest to walk through.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

__all__ = ["bs_price", "bs_greeks", "implied_volatility", "normalise_option_type"]

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


def _is_degenerate(S: float, K: float, T: float, sigma: float) -> bool:
    """Report whether the lognormal has collapsed to a point mass.

    Args:
        S: Underlying spot price.
        K: Strike price.
        T: Time to expiry in years.
        sigma: Annualised volatility.

    Returns:
        True when no diffusion remains, so closed-form d1/d2 are undefined.
    """
    return T <= 0 or sigma <= 0 or S <= 0 or K <= 0


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
        Theoretical option price. Degenerate inputs return intrinsic value.

    Raises:
        ValueError: If ``option_type`` is neither call nor put.

    Example:
        >>> round(bs_price(100, 100, 1.0, 0.05, 0.2, "call"), 2)
        10.45
    """
    option_type = normalise_option_type(option_type)
    if _is_degenerate(S, K, T, sigma):
        return _intrinsic(S, K, option_type)

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
        point. Degenerate inputs return the point-mass Greeks: delta is 1/0 for
        a call and 0/-1 for a put depending on moneyness, everything else zero.
        Exactly at the money the degenerate delta is the limiting value, 0.5 for
        a call and -0.5 for a put, which is the only pair that keeps put-call
        delta parity holding at the tie as it does everywhere else.

    Raises:
        ValueError: If ``option_type`` is neither call nor put.
    """
    option_type = normalise_option_type(option_type)
    if _is_degenerate(S, K, T, sigma):
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
