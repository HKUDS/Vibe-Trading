"""Copula models for non-linear dependency and tail risk analysis.

Implements bivariate Archimedean copulas (Clayton, Gumbel, Frank) and Gaussian copula,
with Kendall's tau calibration and tail dependence coefficients.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from scipy.stats import norm, rankdata

__all__ = [
    "clayton_copula_cdf",
    "clayton_tail_dependence",
    "fit_copula_from_tau",
    "frank_copula_cdf",
    "gaussian_copula_cdf",
    "gumbel_copula_cdf",
    "gumbel_tail_dependence",
    "pseudo_observations",
]


def pseudo_observations(data: np.ndarray) -> np.ndarray:
    """Transform empirical data to uniform [0, 1] pseudo-observations via rank transformation.

    Tied observations receive their average rank, and NaNs remain missing rather
    than being assigned an arbitrary order.

    Args:
        data: 1-D or 2-D array of observations.

    Returns:
        Array of normalized ranks in (0, 1), shape matching ``data``.
    """
    arr = np.asarray(data, dtype=float)
    if arr.ndim not in (1, 2):
        raise ValueError("data must be 1-D or 2-D")
    if np.isinf(arr).any():
        raise ValueError("data must not contain infinite values")

    if arr.ndim == 1:
        result = np.full(arr.shape, np.nan, dtype=float)
        valid = ~np.isnan(arr)
        n = int(valid.sum())
        if n:
            result[valid] = rankdata(arr[valid], method="average") / (n + 1.0)
        return result

    result = np.full(arr.shape, np.nan, dtype=float)
    for column in range(arr.shape[1]):
        valid = ~np.isnan(arr[:, column])
        n = int(valid.sum())
        if n:
            result[valid, column] = rankdata(arr[valid, column], method="average") / (n + 1.0)
    return result


def clayton_copula_cdf(u: float | np.ndarray, v: float | np.ndarray, theta: float) -> float | np.ndarray:
    """Evaluate bivariate Clayton copula CDF: C(u, v) = (u^{-theta} + v^{-theta} - 1)^{-1/theta}.

    Args:
        u: Uniform marginal in (0, 1].
        v: Uniform marginal in (0, 1].
        theta: Parameter > 0 (models lower tail dependence).

    Returns:
        Copula CDF value in [0, 1].
    """
    if theta <= 0.0:
        raise ValueError(f"Clayton parameter theta must be strictly positive, got {theta}")
    u_arr = np.asarray(u, dtype=float)
    v_arr = np.asarray(v, dtype=float)
    if np.any((u_arr <= 0.0) | (u_arr > 1.0) | (v_arr <= 0.0) | (v_arr > 1.0)):
        raise ValueError("u and v marginals must be in (0, 1]")

    # Compute in log space so u^{-theta} never overflows for large theta:
    # log(u^{-theta} + v^{-theta} - 1) = logaddexp(a, b) + log1p(-exp(-logaddexp(a, b)))
    a = -theta * np.log(u_arr)
    b = -theta * np.log(v_arr)
    lse = np.logaddexp(a, b)
    log_inner = lse + np.log1p(-np.exp(-lse))
    val = np.exp(-log_inner / theta)
    return float(val) if np.ndim(val) == 0 else val


def clayton_tail_dependence(theta: float) -> dict[str, float]:
    """Calculate upper and lower tail dependence coefficients for Clayton copula.

    Lower: lambda_L = 2^{-1/theta}, Upper: lambda_U = 0.
    """
    if theta <= 0.0:
        raise ValueError(f"theta must be positive, got {theta}")
    return {
        "lambda_lower": float(2.0 ** (-1.0 / theta)),
        "lambda_upper": 0.0,
    }


def gumbel_copula_cdf(u: float | np.ndarray, v: float | np.ndarray, theta: float) -> float | np.ndarray:
    """Evaluate bivariate Gumbel copula CDF: C(u, v) = exp(-((-ln u)^theta + (-ln v)^theta)^{1/theta}).

    Args:
        u: Uniform marginal in (0, 1].
        v: Uniform marginal in (0, 1].
        theta: Parameter >= 1.0 (models upper tail dependence).
    """
    if theta < 1.0:
        raise ValueError(f"Gumbel parameter theta must be >= 1.0, got {theta}")
    u_arr = np.asarray(u, dtype=float)
    v_arr = np.asarray(v, dtype=float)
    if np.any((u_arr <= 0.0) | (u_arr > 1.0) | (v_arr <= 0.0) | (v_arr > 1.0)):
        raise ValueError("u and v marginals must be in (0, 1]")

    # Compute in log space so (-ln u)^theta never underflows for large theta:
    # log((-ln u)^theta + (-ln v)^theta) = logaddexp(theta*log(-log u), theta*log(-log v))
    # A marginal of exactly 1.0 gives log(-log 1) = log(0) = -inf, which
    # logaddexp handles correctly; silence the divide-by-zero warning.
    with np.errstate(divide="ignore", invalid="ignore"):
        a = theta * np.log(-np.log(u_arr))
        b = theta * np.log(-np.log(v_arr))
    val = np.exp(-np.exp(np.logaddexp(a, b) / theta))
    return float(val) if np.ndim(val) == 0 else val


def gumbel_tail_dependence(theta: float) -> dict[str, float]:
    """Calculate upper and lower tail dependence coefficients for Gumbel copula.

    Upper: lambda_U = 2 - 2^{1/theta}, Lower: lambda_L = 0.
    """
    if theta < 1.0:
        raise ValueError(f"theta must be >= 1.0, got {theta}")
    return {
        "lambda_lower": 0.0,
        "lambda_upper": float(2.0 - 2.0 ** (1.0 / theta)),
    }


def frank_copula_cdf(u: float | np.ndarray, v: float | np.ndarray, theta: float) -> float | np.ndarray:
    """Evaluate bivariate Frank copula CDF: C(u, v) = -1/theta * ln(1 + (exp(-theta*u) - 1)*(exp(-theta*v) - 1)/(exp(-theta) - 1))."""
    if theta == 0.0:
        raise ValueError("Frank parameter theta must be non-zero (theta=0 is independence)")
    u_arr = np.asarray(u, dtype=float)
    v_arr = np.asarray(v, dtype=float)
    if np.any((u_arr <= 0.0) | (u_arr > 1.0) | (v_arr <= 0.0) | (v_arr > 1.0)):
        raise ValueError("u and v marginals must be in (0, 1]")

    # The naive form breaks at both ends of the parameter range, so neither
    # sign keeps it. For theta > 0 it cancels catastrophically (num/den -> -1,
    # log(0) -> -inf); for theta < 0 every factor is positive but
    # (e^{|theta|u} - 1)(e^{|theta|v} - 1) overflows to inf from
    # |theta| ~ 355, which is the same failure the positive branch was fixed
    # for and just as reachable (Kendall tau -> -1 is a real regime).
    if theta > 0:
        s = np.minimum(u_arr, v_arr)
        t = np.maximum(u_arr, v_arr)
        # inner = 1 + e^{-th(t-s)} - e^{-th t} - e^{-th(1-s)} written as a sum
        # of two POSITIVE terms via expm1. Spelled with plain exp it is a
        # 1+1-1-1 cancellation as theta -> 0: at theta=1e-6 it kept ~6 digits,
        # and the 1/theta factor below multiplied that error by 1e6 (C(0.3,0.7)
        # came out 0.20974 against the independence limit 0.21, breaking the
        # Frechet lower bound).
        inner = -(
            np.expm1(-theta * t)
            + np.exp(-theta * (t - s)) * np.expm1(-theta * (1.0 - t))
        )
        log_num = -theta * s + np.log(inner)
        log_den = np.log(-np.expm1(-theta))
        val = -(1.0 / theta) * (log_num - log_den)
    else:
        # phi = -theta > 0. Every term is positive here, so the ratio needs no
        # cancellation guard — only its logarithm, computed with
        # log(e^{phi x} - 1) = phi x + log1p(-e^{-phi x}):
        #   log r = log(e^{phi u} - 1) + log(e^{phi v} - 1) - log(e^{phi} - 1)
        #   C     = log(1 + r) / phi = logaddexp(0, log r) / phi
        phi = -theta
        log_num = (
            phi * u_arr
            + np.log(-np.expm1(-phi * u_arr))
            + phi * v_arr
            + np.log(-np.expm1(-phi * v_arr))
        )
        log_den = phi + np.log(-np.expm1(-phi))
        val = np.logaddexp(0.0, log_num - log_den) / phi
    return float(val) if np.ndim(val) == 0 else val


def gaussian_copula_cdf(u: float, v: float, rho: float) -> float:
    """Evaluate bivariate Gaussian copula CDF."""
    if not (-1.0 < rho < 1.0):
        raise ValueError(f"rho must be strictly in (-1.0, 1.0), got {rho}")
    if not (0.0 < u <= 1.0 and 0.0 < v <= 1.0):
        raise ValueError("u and v must be in (0, 1]")

    from scipy.stats import multivariate_normal

    z1 = float(norm.ppf(u))
    z2 = float(norm.ppf(v))
    cov = [[1.0, rho], [rho, 1.0]]
    val = multivariate_normal.cdf([z1, z2], mean=[0.0, 0.0], cov=cov)
    return float(val)


def fit_copula_from_tau(tau: float, family: Literal["clayton", "gumbel", "gaussian"]) -> dict[str, float]:
    """Calibrate copula parameter from Kendall's rank correlation tau.

    Args:
        tau: Kendall's tau in (-1.0, 1.0).
        family: 'clayton', 'gumbel', or 'gaussian'.

    Returns:
        dict with keys:
            * ``family`` (str)
            * ``theta`` or ``rho`` (float)
            * ``tau`` (float)
    """
    fam = family.strip().lower()
    if fam == "clayton":
        if tau <= 0.0 or tau >= 1.0:
            raise ValueError("Clayton copula requires tau in (0, 1)")
        theta = float(2.0 * tau / (1.0 - tau))
        tail = clayton_tail_dependence(theta)
        return {"family": "clayton", "theta": theta, "tau": tau, **tail}
    elif fam == "gumbel":
        if tau < 0.0 or tau >= 1.0:
            raise ValueError("Gumbel copula requires tau in [0, 1)")
        theta = float(1.0 / (1.0 - tau)) if tau < 1.0 else 1.0
        tail = gumbel_tail_dependence(theta)
        return {"family": "gumbel", "theta": theta, "tau": tau, **tail}
    elif fam == "gaussian":
        if not (-1.0 < tau < 1.0):
            raise ValueError("Gaussian copula requires tau in (-1, 1)")
        # Greiner's relation: rho = sin(pi/2 * tau)
        rho = float(math.sin(math.pi * 0.5 * tau))
        return {"family": "gaussian", "rho": rho, "tau": tau, "lambda_lower": 0.0, "lambda_upper": 0.0}
    else:
        raise ValueError(f"Unsupported family: {family}")
