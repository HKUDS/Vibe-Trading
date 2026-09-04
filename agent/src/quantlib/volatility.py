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

from scipy.integrate import quad
from src.quantlib.options import normalise_option_type

__all__ = [
    "heston_characteristic_function",
    "heston_price",
    "heston_feller_condition",
]


def heston_feller_condition(kappa: float, theta: float, sigma_v: float) -> dict[str, float | bool]:
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
    if sigma_v <= 0.0:
        raise ValueError(f"sigma_v must be strictly positive, got {sigma_v}")
    if kappa <= 0.0 or theta <= 0.0:
        raise ValueError(f"kappa and theta must be strictly positive, got kappa={kappa}, theta={theta}")

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
    integration_limit: float = 200.0,
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
        integration_limit: Upper limit for numerical quadrature.

    Returns:
        Option price as a non-negative float.
    """
    if S0 <= 0.0 or K <= 0.0:
        raise ValueError(f"Spot S0 and strike K must be positive, got S0={S0}, K={K}")
    if T <= 0.0:
        opt_type = normalise_option_type(option_type)
        return float(max(0.0, S0 - K) if opt_type == "call" else max(0.0, K - S0))
    if v0 < 0.0 or kappa <= 0.0 or theta <= 0.0 or sigma_v <= 0.0:
        raise ValueError("v0 must be >= 0, and kappa, theta, sigma_v must be strictly positive")
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
