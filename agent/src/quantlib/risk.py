"""Risk measures: VaR/CVaR, drawdown, Monte Carlo simulation and EVT tail fitting.

SIGN CONVENTION -- read this before using anything here
------------------------------------------------------
**A loss is a positive number.** Every risk *magnitude* this module returns is
non-negative and grows as the risk gets worse:

* ``historical_var`` / ``parametric_var`` -- ``0.028`` means "a 2.8% loss".
* ``historical_cvar`` -- ``0.042`` means "a 4.2% average loss in the tail".
* ``max_drawdown_analysis()["max_drawdown"]`` -- ``0.325`` means "a 32.5%
  peak-to-trough decline". Note this is the opposite of the ``-0.325`` that a
  raw ``(equity / equity.cummax() - 1).min()`` produces; it is flipped here so
  that one rule covers the whole module.
* ``analyze_mc_results()["var"|"cvar"]`` -- same, positive losses.

Quantities that are *returns* rather than *losses* keep their natural sign and
are named ``*_return`` so the two can never be confused: ``mean_return``,
``worst_5pct_return`` and ``best_5pct_return`` are all signed returns, so a bad
outcome there is negative.

The invariant ``cvar >= var`` holds by construction for every pair of measures
computed from the same sample at the same confidence level. Note that this is
**not** ``cvar >= var >= 0``: the magnitudes are not clipped, so a sample whose
tail holds no actual loss reports a *negative* loss, i.e. a gain. Do not assert
non-negativity on a VaR; assert the ordering.

Quantile convention
-------------------
``historical_var`` uses a *non-interpolating lower order statistic*: with the
returns sorted ascending, it takes element ``ceil((1 - confidence) * n) - 1``
and negates it. No blending between neighbouring observations, so the result is
always an actually-observed return. ``historical_cvar`` averages every return at
or below that same order statistic (inclusive), which is the standard expected
shortfall and is what guarantees ``cvar >= var``.
"""

from __future__ import annotations

from collections.abc import Sequence

import math

import numpy as np
import pandas as pd
from scipy.stats import genpareto, norm

__all__ = [
    "historical_var",
    "parametric_var",
    "historical_cvar",
    "max_drawdown_analysis",
    "monte_carlo_gbm",
    "analyze_mc_results",
    "fit_gpd_tail",
]

TRADING_DAYS_PER_YEAR = 252
"""Day count used to annualise drift/volatility and to size a simulation step."""

GPD_SHAPE_SIGNIFICANCE_SIGMAS = 2.0
"""Standard errors a GPD shape must clear before ``fit_gpd_tail`` calls the tail
fat or bounded rather than exponential.

Measured over 200 refits per case: at 2.0 a truly exponential tail is labelled
``"exponential"`` 96.5% of the time, while ``xi = +0.40`` and ``xi = -0.35``
(n=3000) are still labelled correctly 100% of the time and ``xi = +0.10``
(n=2000) 98.5%. At 1.0 the exponential case drops to 70.5%, which is why the
band is not a single standard error.
"""


def _clean_returns(returns: pd.Series | np.ndarray | Sequence[float]) -> np.ndarray:
    """Coerce a return series to a finite 1-D float array.

    Args:
        returns: Return observations as a pandas Series, numpy array or any
            sequence of floats. NaN and infinite values are dropped.

    Returns:
        A 1-D float64 array of the finite observations, in input order.

    Raises:
        ValueError: If the input is not 1-D or holds no finite observation.
    """
    values = np.asarray(returns, dtype=float)
    if values.ndim > 1:
        raise ValueError(f"returns must be 1-D, got shape {values.shape}")
    values = values.ravel()
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("returns contains no finite observation")
    return finite


def _validate_confidence(confidence: float) -> None:
    """Check that a confidence level is a strict probability.

    Args:
        confidence: Confidence level, e.g. 0.95.

    Raises:
        ValueError: If ``confidence`` is not strictly between 0 and 1.
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")


def _validate_horizon(horizon: int) -> None:
    """Check that a holding period is a positive whole number of periods.

    Args:
        horizon: Holding period in periods (days for a daily return series).

    Raises:
        ValueError: If ``horizon`` is less than 1.
    """
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1, got {horizon}")


def _tail_index(n: int, confidence: float) -> int:
    """Position of the VaR order statistic in an ascending-sorted sample.

    Args:
        n: Number of observations, at least 1.
        confidence: Confidence level in (0, 1).

    Returns:
        The index ``ceil((1 - confidence) * n) - 1`` clamped into ``[0, n - 1]``.

        This is the textbook lower quantile. The floor form ``floor((1-c)*n)``
        agrees with it at every confidence level anyone uses -- 0.90, 0.95,
        0.99 and friends are not exact binary fractions, so ``(1-c)*n`` is never
        exactly an integer and the two expressions coincide. They diverge only
        at levels like 0.5, 0.6 and 0.75, where the floor form picks the next
        observation up and understates the loss. Being right by construction
        rather than by floating-point accident costs nothing here.
    """
    return int(min(max(math.ceil((1.0 - confidence) * n) - 1, 0), n - 1))


def historical_var(
    returns: pd.Series | np.ndarray | Sequence[float],
    confidence: float = 0.95,
    horizon: int = 1,
) -> float:
    """Value at Risk from the empirical distribution of past returns.

    Makes no distributional assumption: it simply reads the loss off the sorted
    sample at the ``1 - confidence`` order statistic (see the module docstring
    for the exact, non-interpolating convention).

    Args:
        returns: Periodic (usually daily) return series.
        confidence: Confidence level, commonly 0.95 or 0.99.
        horizon: Holding period in periods, scaled by the square-root-of-time
            rule. That rule assumes i.i.d. returns and understates risk when
            returns are autocorrelated.

    Returns:
        The VaR as a positive loss magnitude, e.g. 0.028 for a 2.8% loss. A
        sample with no losses in the tail yields a negative-signed "loss", i.e.
        a gain, which is reported as-is rather than clipped.

    Raises:
        ValueError: If ``returns`` has no finite observation, ``confidence`` is
            outside (0, 1), or ``horizon`` is below 1.
    """
    _validate_confidence(confidence)
    _validate_horizon(horizon)
    values = np.sort(_clean_returns(returns))
    quantile_return = values[_tail_index(values.size, confidence)]
    return float(-quantile_return * np.sqrt(horizon))


def parametric_var(
    returns: pd.Series | np.ndarray | Sequence[float],
    confidence: float = 0.95,
    horizon: int = 1,
) -> float:
    """Value at Risk under a fitted normal distribution.

    Cheap and smooth, but it sees only a mean and a variance, so it misses fat
    tails. The direction of that error depends on the confidence level and is
    not uniform: a fat tail inflates the fitted sigma, which pushes the normal
    quantile *outward* at moderate confidence, where the empirical quantile is
    still in the well-behaved body. Measured over 300 t(4) samples of 750 daily
    returns, this function reads *above* ``historical_var`` in 100% of samples
    at 90% confidence and 92.7% at 95%, and only *below* it -- the classic
    understatement -- in 94.7% of samples at 99%. Compare the two at 99% or
    deeper if the point is to expose the tail.

    Args:
        returns: Periodic (usually daily) return series. The mean and the
            sample standard deviation (ddof=1) are estimated from it.
        confidence: Confidence level, commonly 0.95 or 0.99.
        horizon: Holding period in periods, scaled by square-root-of-time.

    Returns:
        The VaR as a positive loss magnitude: ``-(mu + z * sigma) * sqrt(horizon)``
        where ``z = norm.ppf(1 - confidence)``.

    Raises:
        ValueError: If ``returns`` holds fewer than two finite observations,
            ``confidence`` is outside (0, 1), or ``horizon`` is below 1.
    """
    _validate_confidence(confidence)
    _validate_horizon(horizon)
    values = _clean_returns(returns)
    if values.size < 2:
        raise ValueError("parametric_var needs at least 2 observations for a std estimate")
    mu = float(values.mean())
    sigma = float(values.std(ddof=1))
    z = float(norm.ppf(1.0 - confidence))
    return float(-(mu + z * sigma) * np.sqrt(horizon))


def historical_cvar(
    returns: pd.Series | np.ndarray | Sequence[float],
    confidence: float = 0.95,
    horizon: int = 1,
) -> float:
    """Conditional VaR (expected shortfall) from the empirical distribution.

    The average loss *given* that the VaR threshold was breached. Unlike VaR it
    is subadditive, so it can be decomposed across a portfolio, which is why
    Basel III moved to it.

    Args:
        returns: Periodic (usually daily) return series.
        confidence: Confidence level, commonly 0.95 or 0.99.
        horizon: Holding period in periods, scaled by square-root-of-time.

    Returns:
        The CVaR as a positive loss magnitude. Always greater than or equal to
        ``historical_var`` on the same inputs, because it averages the VaR order
        statistic together with everything worse than it.

    Raises:
        ValueError: If ``returns`` has no finite observation, ``confidence`` is
            outside (0, 1), or ``horizon`` is below 1.
    """
    _validate_confidence(confidence)
    _validate_horizon(horizon)
    values = np.sort(_clean_returns(returns))
    tail = values[: _tail_index(values.size, confidence) + 1]
    return float(-tail.mean() * np.sqrt(horizon))


def max_drawdown_analysis(equity: pd.Series | np.ndarray | Sequence[float]) -> dict:
    """Locate the worst peak-to-trough decline of an equity curve and its recovery.

    Args:
        equity: Net-value / equity series, strictly positive. A pandas Series
            keeps its index, so ``peak_date`` and friends come back as index
            labels; anything else is wrapped in a RangeIndex and the ``*_days``
            calendar fields are then None.

    Returns:
        dict with keys:
            max_drawdown (float): Worst decline as a **positive** fraction, so
                0.25 means the curve fell 25% below its running peak. 0.0 when
                the curve never declines.
            peak_date: Index label of the running peak preceding the trough.
            trough_date: Index label of the deepest point.
            recovery_date: Index label of the first observation at or above the
                peak value, searched from the trough onward; None if the series
                ends still underwater.
            recovered (bool): Whether ``recovery_date`` was found.
            peak_to_trough_periods (int): Observations from peak to trough.
            trough_to_recovery_periods (int | None): Observations from trough to
                recovery, None if never recovered.
            underwater_days (int | None): Calendar days peak to trough; None
                unless the index is a DatetimeIndex.
            recovery_days (int | None): Calendar days trough to recovery; None
                unless the index is a DatetimeIndex and recovery happened.

    Raises:
        ValueError: If ``equity`` is not one-dimensional, has no finite
            observation, or any value is not strictly positive (a drawdown ratio
            is undefined at or below zero).
    """
    if not isinstance(equity, pd.Series):
        array = np.asarray(equity, dtype=float)
        if array.ndim > 1:
            # Flattening an (n, k) matrix concatenates unrelated curves into one
            # nonsense path and reports a drawdown for it. _clean_returns
            # already refuses this shape; refuse it here too.
            raise ValueError(f"equity must be 1-D, got shape {array.shape}")
        equity = pd.Series(array)
    series = equity
    series = series.astype(float)
    series = series[np.isfinite(series.to_numpy())]
    if series.empty:
        raise ValueError("equity contains no finite observation")
    values = series.to_numpy()
    if (values <= 0.0).any():
        raise ValueError("equity must be strictly positive to express drawdown as a fraction")

    running_peak = np.maximum.accumulate(values)
    drawdown = values / running_peak - 1.0  # <= 0 everywhere
    trough_pos = int(np.argmin(drawdown))
    peak_pos = int(np.argmax(values[: trough_pos + 1]))

    # A flat/rising curve has drawdown 0 at the trough, so the trough itself
    # already satisfies "back at the peak" and recovery is instantaneous.
    at_or_above_peak = np.flatnonzero(values[trough_pos:] >= values[peak_pos])
    recovery_pos = int(trough_pos + at_or_above_peak[0]) if at_or_above_peak.size else None

    index = series.index
    is_dated = isinstance(index, pd.DatetimeIndex)
    return {
        "max_drawdown": float(-drawdown[trough_pos]),
        "peak_date": index[peak_pos],
        "trough_date": index[trough_pos],
        "recovery_date": index[recovery_pos] if recovery_pos is not None else None,
        "recovered": recovery_pos is not None,
        "peak_to_trough_periods": trough_pos - peak_pos,
        "trough_to_recovery_periods": None if recovery_pos is None else recovery_pos - trough_pos,
        "underwater_days": int((index[trough_pos] - index[peak_pos]).days) if is_dated else None,
        "recovery_days": (
            int((index[recovery_pos] - index[trough_pos]).days)
            if is_dated and recovery_pos is not None
            else None
        ),
    }


def monte_carlo_gbm(
    s0: float,
    mu: float,
    sigma: float,
    n_steps: int = TRADING_DAYS_PER_YEAR,
    n_paths: int = 10_000,
    *,
    seed: int | None = None,
    steps_per_year: int = TRADING_DAYS_PER_YEAR,
) -> np.ndarray:
    """Simulate price paths under geometric Brownian motion.

    Each step applies ``(mu - 0.5 * sigma**2) * dt + sigma * sqrt(dt) * Z`` in
    log space, so the terminal expectation is ``s0 * exp(mu * n_steps / steps_per_year)``.

    Args:
        s0: Initial price, strictly positive.
        mu: Annualised drift of the arithmetic return.
        sigma: Annualised volatility, non-negative. Zero gives a deterministic
            path, which is useful as a test fixture.
        n_steps: Number of simulated steps, at least 1.
        n_paths: Number of paths, at least 1. Use 10,000 or more before reading
            anything off the tail.
        seed: Seed for ``numpy.random.default_rng``. Keyword-only. Pass an int
            for a reproducible run; None draws fresh OS entropy and the result
            is then NOT reproducible.
        steps_per_year: Steps per year, i.e. ``dt = 1 / steps_per_year``.
            Defaults to the 252-day trading year.

    Returns:
        Price matrix of shape ``(n_paths, n_steps + 1)``. Column 0 is exactly
        ``s0`` on every path, so ``paths[:, -1] / paths[:, 0] - 1`` is the total
        return over the whole simulation.

    Raises:
        ValueError: If ``s0`` is not positive, ``sigma`` is negative, or any of
            ``n_steps`` / ``n_paths`` / ``steps_per_year`` is below 1.
    """
    if s0 <= 0.0:
        raise ValueError(f"s0 must be > 0, got {s0}")
    if sigma < 0.0:
        raise ValueError(f"sigma must be >= 0, got {sigma}")
    if n_steps < 1 or n_paths < 1:
        raise ValueError(f"n_steps and n_paths must be >= 1, got {n_steps} and {n_paths}")
    if steps_per_year < 1:
        raise ValueError(f"steps_per_year must be >= 1, got {steps_per_year}")

    dt = 1.0 / steps_per_year
    rng = np.random.default_rng(seed)
    shocks = rng.standard_normal((n_paths, n_steps))
    log_returns = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * shocks
    paths = np.empty((n_paths, n_steps + 1), dtype=float)
    paths[:, 0] = s0
    paths[:, 1:] = s0 * np.exp(np.cumsum(log_returns, axis=1))
    return paths


def analyze_mc_results(paths: np.ndarray, confidence: float = 0.95) -> dict:
    """Summarise the terminal distribution of a simulated price matrix.

    Args:
        paths: Price matrix of shape ``(n_paths, n_steps + 1)`` as returned by
            ``monte_carlo_gbm``; column 0 is the starting price.
        confidence: Confidence level for the VaR/CVaR of the terminal return.

    Returns:
        dict with keys:
            mean_return, median_return, std_return (float): Signed total
                returns over the simulation, so a bad outcome is negative.
            var, cvar (float): Positive loss magnitudes, computed with the same
                order-statistic convention as ``historical_var`` /
                ``historical_cvar``, so ``cvar >= var``.
            prob_loss (float): Fraction of paths ending below their start.
            worst_5pct_return, best_5pct_return (float): Signed 5th and 95th
                percentiles of the terminal return (linear interpolation).

    Raises:
        ValueError: If ``paths`` is not 2-D with at least two columns, holds a
            non-positive starting price, or ``confidence`` is outside (0, 1).
    """
    _validate_confidence(confidence)
    matrix = np.asarray(paths, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] < 2:
        raise ValueError(f"paths must be 2-D with >= 2 columns, got shape {matrix.shape}")
    start = matrix[:, 0]
    if (start <= 0.0).any():
        raise ValueError("paths column 0 (the starting price) must be strictly positive")

    returns = matrix[:, -1] / start - 1.0
    return {
        "mean_return": float(np.mean(returns)),
        "median_return": float(np.median(returns)),
        "std_return": float(np.std(returns, ddof=1)) if returns.size > 1 else 0.0,
        "var": historical_var(returns, confidence),
        "cvar": historical_cvar(returns, confidence),
        "prob_loss": float(np.mean(returns < 0.0)),
        "worst_5pct_return": float(np.percentile(returns, 5.0)),
        "best_5pct_return": float(np.percentile(returns, 95.0)),
    }


def fit_gpd_tail(
    returns: pd.Series | np.ndarray | Sequence[float],
    threshold_pct: float = 5.0,
) -> dict:
    """Fit the loss tail with a generalised Pareto distribution (POT method).

    Extreme value theory says the exceedances over a high enough threshold
    converge to a GPD regardless of the parent distribution, which is what makes
    this usable where a normal fit is not. The location is pinned at zero
    because exceedances are non-negative by construction.

    ``tail_type`` is decided against ``shape_stderr``, not against exact zero. A
    maximum-likelihood shape is a float and is therefore never exactly ``0.0``,
    so a hard ``shape > 0`` test would label a genuinely exponential tail "fat"
    or "bounded" on the sign of estimation noise alone and would make the
    ``"exponential"`` label unreachable in practice.

    Args:
        returns: Periodic (usually daily) return series.
        threshold_pct: Percentile defining the left tail, e.g. 5.0 keeps the
            worst 5% of returns. Must be in (0, 100).

    Returns:
        dict with keys:
            threshold (float): The signed return at ``threshold_pct``; losses
                worse than this are the exceedances.
            n_exceedances (int): Number of observations in the tail.
            exceedance_rate (float): ``n_exceedances / n_observations``.
            shape_xi (float): GPD shape. ``> 0`` fat tail, ``== 0`` exponential
                tail, ``< 0`` bounded tail.
            shape_stderr (float): Asymptotic standard error of ``shape_xi``,
                ``|1 + xi| / sqrt(n_exceedances)``. Only valid for ``xi > -0.5``;
                below that the GPD likelihood is non-regular and the figure is
                indicative at best.
            scale_sigma (float): GPD scale, in units of loss magnitude.
            tail_type (str): ``"fat"`` when ``shape_xi`` clears
                ``GPD_SHAPE_SIGNIFICANCE_SIGMAS * shape_stderr``, ``"bounded"``
                when it clears it on the negative side, otherwise
                ``"exponential"`` -- i.e. a shape indistinguishable from zero at
                this sample size is reported as exponential rather than being
                rounded into one of the two extremes.

    Raises:
        ValueError: If ``threshold_pct`` is outside (0, 100), ``returns`` has no
            finite observation, or the threshold leaves fewer than 2 exceedances
            to fit.
    """
    if not 0.0 < threshold_pct < 100.0:
        raise ValueError(f"threshold_pct must be in (0, 100), got {threshold_pct}")
    values = _clean_returns(returns)
    threshold = float(np.percentile(values, threshold_pct))
    # Exceedances are loss magnitudes, hence non-negative: a positive number is
    # "how far below the threshold this return fell".
    exceedances = threshold - values[values < threshold]
    if exceedances.size < 2:
        raise ValueError(
            f"need at least 2 exceedances to fit a GPD, got {exceedances.size} "
            f"at threshold_pct={threshold_pct}"
        )

    shape, _loc, scale = genpareto.fit(exceedances, floc=0.0)
    # Asymptotic MLE standard error of the GPD shape. Empirically checked
    # against the spread of 12 refits per shape at n=2000: predicted
    # 0.0291/0.0246/0.0224/0.0179 vs observed 0.0313/0.0244/0.0212/0.0162 for
    # true xi of +0.30/+0.10/0.00/-0.20.
    shape_stderr = float(abs(1.0 + shape) / np.sqrt(exceedances.size))
    band = GPD_SHAPE_SIGNIFICANCE_SIGMAS * shape_stderr
    if shape > band:
        tail_type = "fat"
    elif shape < -band:
        tail_type = "bounded"
    else:
        tail_type = "exponential"
    return {
        "threshold": threshold,
        "n_exceedances": int(exceedances.size),
        "exceedance_rate": float(exceedances.size / values.size),
        "shape_xi": float(shape),
        "shape_stderr": shape_stderr,
        "scale_sigma": float(scale),
        "tail_type": tail_type,
    }
