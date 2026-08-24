"""Fixed-income primitives: day count conventions, bond pricing, risk metrics, and yield curve fitting.

All rates are decimals, maturities/horizons are in years, and duration/convexity
metrics are in years or years squared.
"""

from __future__ import annotations

import datetime as _dt
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq, minimize

__all__ = [
    "DAY_COUNT_CONVENTIONS",
    "DEFAULT_DAY_COUNT",
    "COMPOUNDING_CONVENTIONS",
    "DEFAULT_COMPOUNDING",
    "DEFAULT_KEY_RATE_TENORS",
    "CurveFit",
    "year_fraction",
    "accrued_interest",
    "bond_cashflows",
    "bond_price",
    "ytm_solve",
    "macaulay_duration",
    "modified_duration",
    "key_rate_duration",
    "convexity",
    "dv01",
    "effective_duration",
    "nelson_siegel",
    "svensson",
    "fit_yield_curve",
]

#: Day-count conventions understood by :func:`year_fraction`.
DAY_COUNT_CONVENTIONS: tuple[str, ...] = (
    "ACT/365F",
    "ACT/360",
    "ACT/ACT",
    "30/360",
    "30E/360",
)

#: Convention assumed when the caller does not name one.
DEFAULT_DAY_COUNT: str = "ACT/365F"

#: Compounding conventions understood by the pricing functions.
COMPOUNDING_CONVENTIONS: tuple[str, ...] = ("discrete", "continuous")

#: Compounding assumed when the caller does not name one (the markdown's behaviour).
DEFAULT_COMPOUNDING: str = "discrete"

#: Standard benchmark tenors for Key Rate Duration decomposition.
DEFAULT_KEY_RATE_TENORS: tuple[float, ...] = (
    0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0
)

def year_fraction(
    start: _dt.date,
    end: _dt.date,
    day_count: str = DEFAULT_DAY_COUNT,
) -> float:
    """Accrual factor between two dates under a named day-count convention.

    Args:
        start: Period start (accrual runs from this date, inclusive).
        end: Period end (accrual runs to this date, exclusive).
        day_count: One of :data:`DAY_COUNT_CONVENTIONS`. ``ACT/ACT`` is the
            ISDA variant: each calendar year contributes
            ``days_in_that_year / (365 or 366)``.

    Returns:
        Year fraction as a float. Negative if ``end`` precedes ``start``.

    Raises:
        ValueError: If ``day_count`` is not a recognised convention.
    """
    if day_count not in DAY_COUNT_CONVENTIONS:
        raise ValueError(
            f"unknown day_count {day_count!r}; expected one of {DAY_COUNT_CONVENTIONS}"
        )

    if end < start:
        return -year_fraction(end, start, day_count)

    if day_count == "ACT/365F":
        return (end - start).days / 365.0
    if day_count == "ACT/360":
        return (end - start).days / 360.0
    if day_count in ("30/360", "30E/360"):
        d1, d2 = start.day, end.day
        if day_count == "30/360":
            # US bond basis: clip D1 to 30, then clip D2 when adjusted D1 is 30.
            if d1 == 31:
                d1 = 30
            if d2 == 31 and d1 == 30:
                d2 = 30
        else:  # 30E/360 (Eurobond basis) clips both legs unconditionally.
            d1 = min(d1, 30)
            d2 = min(d2, 30)
        months = 12 * (end.year - start.year) + (end.month - start.month)
        return (30.0 * months + (d2 - d1)) / 360.0

    # ACT/ACT (ISDA): accumulate each calendar year against its own basis.
    total = 0.0
    cursor = start
    while cursor < end:
        year_end = _dt.date(cursor.year + 1, 1, 1)
        chunk_end = min(year_end, end)
        basis = 366.0 if _is_leap(cursor.year) else 365.0
        total += (chunk_end - cursor).days / basis
        cursor = chunk_end
    return total


def _is_leap(year: int) -> bool:
    """Report whether a Gregorian year is a leap year.

    Args:
        year: Four-digit calendar year.

    Returns:
        True when the year has 366 days.
    """
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def accrued_interest(
    face: float,
    coupon_rate: float,
    freq: int,
    last_coupon: _dt.date,
    settlement: _dt.date,
    next_coupon: _dt.date,
    day_count: str = DEFAULT_DAY_COUNT,
) -> float:
    """Interest earned by the seller between the last coupon and settlement.

    Dirty price = clean price + accrued interest. :func:`bond_price` returns the
    price on a coupon date, where accrued interest is zero by construction; use
    this function to move a mid-period settlement onto that basis.

    Args:
        face: Par amount the coupon is computed on.
        coupon_rate: Annual coupon rate as a decimal.
        freq: Coupon payments per year (1 = annual, 2 = semi-annual).
        last_coupon: Date of the most recent coupon payment.
        settlement: Settlement date of the trade.
        next_coupon: Date of the upcoming coupon payment.
        day_count: One of :data:`DAY_COUNT_CONVENTIONS`.

    Returns:
        Accrued interest in the same currency units as ``face``.

    Raises:
        ValueError: If ``freq`` is not positive, if the coupon dates are not
            ordered, or if ``settlement`` falls outside the coupon period.
    """
    if freq <= 0:
        raise ValueError(f"freq must be positive, got {freq}")
    if not last_coupon < next_coupon:
        raise ValueError("last_coupon must precede next_coupon")
    if not last_coupon <= settlement <= next_coupon:
        raise ValueError("settlement must fall inside [last_coupon, next_coupon]")

    period = year_fraction(last_coupon, next_coupon, day_count)
    if period == 0.0:
        return 0.0
    elapsed = year_fraction(last_coupon, settlement, day_count)
    return face * coupon_rate / freq * (elapsed / period)


def bond_cashflows(
    face: float,
    coupon_rate: float,
    n_periods: int,
    freq: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """Coupon schedule of a bullet bond, in periods and amounts.

    Args:
        face: Redemption amount paid with the final coupon.
        coupon_rate: Annual coupon rate as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.

    Returns:
        Tuple ``(periods, amounts)`` where ``periods`` is ``1..n_periods`` as
        floats and ``amounts`` is the cash paid at each. Time in years is
        ``periods / freq``.

    Raises:
        ValueError: If ``face`` is not positive, if ``n_periods`` is not a
            positive integer, or if ``freq`` is not positive.
    """
    if face <= 0:
        raise ValueError(f"face must be positive, got {face}")
    if isinstance(n_periods, bool) or not isinstance(n_periods, (int, np.integer)) or n_periods <= 0:
        raise ValueError(f"n_periods must be a positive integer, got {n_periods!r}")
    if freq <= 0:
        raise ValueError(f"freq must be positive, got {freq}")

    periods = np.arange(1, n_periods + 1, dtype=float)
    amounts = np.full(n_periods, face * coupon_rate / freq, dtype=float)
    amounts[-1] += face
    return periods, amounts


def _discount_factors(
    ytm: float,
    periods: np.ndarray,
    freq: int,
    compounding: str,
) -> np.ndarray:
    """Compute discount factors for period indices under discrete or continuous compounding."""
    if compounding == "discrete":
        periodic = 1.0 + ytm / freq
        if periodic <= 0.0:
            raise ValueError(
                f"discrete compounding needs 1 + ytm/freq > 0, got {periodic}"
            )
        return periodic ** (-periods)
    if compounding == "continuous":
        return np.exp(-ytm * periods / freq)
    raise ValueError(
        f"unknown compounding {compounding!r}; expected one of {COMPOUNDING_CONVENTIONS}"
    )


def bond_price(
    face: float,
    coupon_rate: float,
    ytm: float,
    n_periods: int,
    freq: int = 1,
    compounding: str = DEFAULT_COMPOUNDING,
) -> float:
    """Present value of a bullet bond settling on a coupon date.

    The result is a *clean* price: settlement is assumed to sit on a coupon date
    so no interest has accrued. Add :func:`accrued_interest` for a dirty price.

    Args:
        face: Par/redemption amount, conventionally 100.
        coupon_rate: Annual coupon rate as a decimal (0.05 == 5%).
        ytm: Annual yield to maturity as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year (1 = annual, 2 = semi-annual).
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`.

    Returns:
        Present value in the same units as ``face``.

    Raises:
        ValueError: If the schedule arguments or ``compounding`` are invalid.
    """
    periods, amounts = bond_cashflows(face, coupon_rate, n_periods, freq)
    return float(amounts @ _discount_factors(ytm, periods, freq, compounding))


def ytm_solve(
    price: float,
    face: float,
    coupon_rate: float,
    n_periods: int,
    freq: int = 1,
    compounding: str = DEFAULT_COMPOUNDING,
    bracket: tuple[float, float] = (-0.5, 10.0),
) -> float:
    """Invert :func:`bond_price` for the yield that reproduces a market price.

    Args:
        price: Observed price, on the same clean basis as :func:`bond_price`.
        face: Par/redemption amount.
        coupon_rate: Annual coupon rate as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`.
        bracket: ``(low, high)`` annual yield search interval as decimals.

    Returns:
        Annual yield to maturity as a decimal.

    Raises:
        ValueError: If the price is not reachable inside ``bracket``.
    """
    low, high = bracket
    if low >= high:
        raise ValueError(f"bracket must be increasing, got {bracket}")

    def pv_diff(y: float) -> float:
        return bond_price(face, coupon_rate, y, n_periods, freq, compounding) - price

    try:
        return float(brentq(pv_diff, low, high))
    except ValueError as exc:
        raise ValueError(
            f"no yield in {bracket} reprices this bond to {price}: {exc}"
        ) from exc


def macaulay_duration(
    face: float,
    coupon_rate: float,
    ytm: float,
    n_periods: int,
    freq: int = 1,
    compounding: str = DEFAULT_COMPOUNDING,
) -> float:
    """Present-value-weighted average time to the bond's cash flows.

    Args:
        face: Par/redemption amount.
        coupon_rate: Annual coupon rate as a decimal.
        ytm: Annual yield to maturity as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`.

    Returns:
        Macaulay duration in **years**.

    Raises:
        ValueError: If the schedule arguments or ``compounding`` are invalid.
    """
    periods, amounts = bond_cashflows(face, coupon_rate, n_periods, freq)
    pv = amounts * _discount_factors(ytm, periods, freq, compounding)
    return float((periods / freq) @ pv / pv.sum())


def modified_duration(
    face: float,
    coupon_rate: float,
    ytm: float,
    n_periods: int,
    freq: int = 1,
    compounding: str = DEFAULT_COMPOUNDING,
) -> float:
    """Semi-elasticity of price to yield, ``-(dP/dy)/P``.

    Args:
        face: Par/redemption amount.
        coupon_rate: Annual coupon rate as a decimal.
        ytm: Annual yield to maturity as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`. Under continuous
            compounding modified duration equals Macaulay duration.

    Returns:
        Modified duration in years, positive for a conventional bond.

    Raises:
        ValueError: If the schedule arguments or ``compounding`` are invalid.
    """
    d_mac = macaulay_duration(face, coupon_rate, ytm, n_periods, freq, compounding)
    if compounding == "continuous":
        return d_mac
    return d_mac / (1.0 + ytm / freq)


def key_rate_duration(
    face: float,
    coupon_rate: float,
    ytm: float,
    n_periods: int,
    freq: int = 1,
    key_rates: Sequence[float] = DEFAULT_KEY_RATE_TENORS,
    compounding: str = DEFAULT_COMPOUNDING,
) -> dict[float, float]:
    """Decompose bond yield sensitivity into Key Rate Durations (KRD) across benchmark tenors.

    Distributes cash flow sensitivities to adjacent key rates with triangular kernels.
    Sum of key rate durations equals modified duration.
    Args:
        face: Par/redemption amount.
        coupon_rate: Annual coupon rate as a decimal.
        ytm: Annual yield to maturity as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.
        key_rates: Sequence of key rate tenors in years (strictly increasing).
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`.

    Returns:
        Dict mapping each key rate tenor (float) to its Key Rate Duration (float in years).

    Raises:
        ValueError: If key_rates is empty or not strictly increasing, or schedule/compounding invalid.
    """
    kr = np.asarray(key_rates, dtype=float)
    if kr.size == 0:
        raise ValueError("key_rates must contain at least one tenor")
    if (np.diff(kr) <= 0.0).any():
        raise ValueError(f"key_rates must be strictly increasing, got {key_rates}")

    periods, amounts = bond_cashflows(face, coupon_rate, n_periods, freq)
    pv = amounts * _discount_factors(ytm, periods, freq, compounding)
    price = float(pv.sum())
    if price <= 0.0:
        raise ValueError("bond price must be positive for key rate duration")

    cf_times = periods / freq
    # Modified discount factor weight per cash flow
    if compounding == "continuous":
        time_weights = cf_times
    else:
        time_weights = cf_times / (1.0 + ytm / freq)

    cf_durations = time_weights * pv / price  # Sums to modified duration

    krd_result: dict[float, float] = {float(t): 0.0 for t in kr}

    for t_cf, dur_cf in zip(cf_times, cf_durations):
        if t_cf <= kr[0]:
            krd_result[float(kr[0])] += float(dur_cf)
        elif t_cf >= kr[-1]:
            krd_result[float(kr[-1])] += float(dur_cf)
        else:
            # Find interval kr[k] <= t_cf <= kr[k+1]
            idx = int(np.searchsorted(kr, t_cf))
            t_left = kr[idx - 1]
            t_right = kr[idx]
            w_right = (t_cf - t_left) / (t_right - t_left)
            w_left = 1.0 - w_right
            krd_result[float(t_left)] += float(dur_cf * w_left)
            krd_result[float(t_right)] += float(dur_cf * w_right)

    return krd_result


def convexity(
    face: float,
    coupon_rate: float,
    ytm: float,
    n_periods: int,
    freq: int = 1,
    compounding: str = DEFAULT_COMPOUNDING,
) -> float:
    """Second-order price sensitivity to yield, ``(d2P/dy2)/P``.

    Args:
        face: Par/redemption amount.
        coupon_rate: Annual coupon rate as a decimal.
        ytm: Annual yield to maturity as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`.

    Returns:
        Convexity in years squared. Positive for any bond without embedded
        short optionality.

    Raises:
        ValueError: If the schedule arguments or ``compounding`` are invalid.
    """
    periods, amounts = bond_cashflows(face, coupon_rate, n_periods, freq)
    discounts = _discount_factors(ytm, periods, freq, compounding)
    pv = amounts * discounts
    price = pv.sum()
    if compounding == "continuous":
        return float(((periods / freq) ** 2) @ pv / price)
    weights = periods * (periods + 1.0) / (freq**2)
    return float(weights @ pv / price / (1.0 + ytm / freq) ** 2)


def dv01(
    face: float,
    coupon_rate: float,
    ytm: float,
    n_periods: int,
    freq: int = 1,
    par_amount: float = 1_000_000.0,
    compounding: str = DEFAULT_COMPOUNDING,
) -> float:
    """Cash value of one basis point on a stated par position.

    Args:
        face: Par/redemption amount the quoted price is per, conventionally 100.
        coupon_rate: Annual coupon rate as a decimal.
        ytm: Annual yield to maturity as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.
        par_amount: Par value held. The market value hedged is
            ``par_amount * price / face``.
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`.

    Returns:
        Price change, in currency units, for a 1bp rise in yield, reported as a
        positive number.

    Raises:
        ValueError: If ``face`` is zero, or the schedule/compounding is invalid.
    """
    if face == 0:
        raise ValueError("face must be non-zero")
    d_mod = modified_duration(face, coupon_rate, ytm, n_periods, freq, compounding)
    price = bond_price(face, coupon_rate, ytm, n_periods, freq, compounding)
    return d_mod * (price / face) * 1e-4 * par_amount


def effective_duration(
    reprice: Callable[[float], float],
    yield_level: float,
    bump: float = 1e-4,
) -> float:
    """Duration by symmetric repricing, valid for bonds with embedded options.

    Re-evaluates a custom pricing model at perturbed yields to compute duration.
    Args:
        reprice: Callable mapping a yield level to a price. It must contain the
            option/prepayment logic; nothing here inspects it.
        yield_level: Base yield to bump around.
        bump: Half-width of the symmetric shock, as a decimal (1e-4 = 1bp).

    Returns:
        Effective duration in years, ``(P_down - P_up) / (2 * P_0 * bump)``.

    Raises:
        ValueError: If ``bump`` is not positive or the base price is zero.
    """
    if bump <= 0:
        raise ValueError(f"bump must be positive, got {bump}")
    base = reprice(yield_level)
    if base == 0:
        raise ValueError("base price is zero; effective duration is undefined")
    down = reprice(yield_level - bump)
    up = reprice(yield_level + bump)
    return (down - up) / (2.0 * base * bump)


def _decay_factors(tau: np.ndarray, lam: float) -> tuple[np.ndarray, np.ndarray]:
    """Compute Nelson-Siegel slope and curvature loadings for decay parameter lam."""
    if lam <= 0:
        raise ValueError(f"decay parameter must be positive, got {lam}")
    x = tau / lam
    safe = np.where(x > 0, x, 1.0)
    slope = np.where(x > 0, (1.0 - np.exp(-safe)) / safe, 1.0)
    return slope, slope - np.exp(-x)


def _as_tau(tau: float | Sequence[float] | np.ndarray) -> tuple[np.ndarray, bool]:
    """Normalise scalar or sequence maturity argument to a 1-D float array."""
    arr = np.asarray(tau, dtype=float)
    was_scalar = arr.ndim == 0
    arr = np.atleast_1d(arr)
    if np.any(arr < 0):
        raise ValueError("maturities must be non-negative")
    return arr, was_scalar


def nelson_siegel(
    tau: float | Sequence[float] | np.ndarray,
    beta0: float,
    beta1: float,
    beta2: float,
    lambda1: float,
) -> float | np.ndarray:
    """Compute Nelson-Siegel zero rates for given maturities and parameters."""
    arr, was_scalar = _as_tau(tau)
    slope, curve = _decay_factors(arr, lambda1)
    out = beta0 + beta1 * slope + beta2 * curve
    return float(out[0]) if was_scalar else out


def svensson(
    tau: float | Sequence[float] | np.ndarray,
    beta0: float,
    beta1: float,
    beta2: float,
    beta3: float,
    lambda1: float,
    lambda2: float,
) -> float | np.ndarray:
    """Compute Svensson zero rates for given maturities and parameters."""
    arr, was_scalar = _as_tau(tau)
    slope, curve1 = _decay_factors(arr, lambda1)
    _, curve2 = _decay_factors(arr, lambda2)
    out = beta0 + beta1 * slope + beta2 * curve1 + beta3 * curve2
    return float(out[0]) if was_scalar else out


#: Search range, in years, for the Nelson-Siegel/Svensson decay parameters.
CURVE_DECAY_BOUNDS: tuple[float, float] = (0.05, 30.0)

#: Number of grid points per decay parameter used to seed the curve fit.
CURVE_DECAY_GRID: int = 48


@dataclass(frozen=True)
class CurveFit:
    """Result of :func:`fit_yield_curve`; call it to evaluate the fitted curve.

    Attributes:
        model: ``"nelson_siegel"`` or ``"svensson"``.
        params: Fitted parameters. Nelson-Siegel is
            ``(beta0, beta1, beta2, lambda1)``; Svensson is
            ``(beta0, beta1, beta2, beta3, lambda1, lambda2)``.
        rmse: Root-mean-square fitting error against input yields.
    """

    model: str
    params: tuple[float, ...]
    rmse: float = math.nan

    def __call__(
        self, tau: float | Sequence[float] | np.ndarray
    ) -> float | np.ndarray:
        """Evaluate the fitted curve at one or more maturities.

        Args:
            tau: Maturity or maturities in years.

        Returns:
            Zero rate(s) as decimals.

        Raises:
            ValueError: If the stored model name is not recognised.
        """
        if self.model == "nelson_siegel":
            return nelson_siegel(tau, *self.params)
        if self.model == "svensson":
            return svensson(tau, *self.params)
        raise ValueError(f"unknown curve model {self.model!r}")


def _curve_design(tau: np.ndarray, lambdas: Sequence[float]) -> np.ndarray:
    """Linear design matrix for a curve model with fixed decay parameters.

    Args:
        tau: Maturities in years.
        lambdas: One decay parameter for Nelson-Siegel, two for Svensson.

    Returns:
        Matrix whose columns are the level, slope and curvature loadings.

    Raises:
        ValueError: If a decay parameter is not positive.
    """
    slope, curve1 = _decay_factors(tau, lambdas[0])
    columns = [np.ones_like(tau), slope, curve1]
    for lam in lambdas[1:]:
        columns.append(_decay_factors(tau, lam)[1])
    return np.column_stack(columns)


def _profiled_ssr(
    lambdas: Sequence[float], tau: np.ndarray, yields: np.ndarray
) -> tuple[float, np.ndarray]:
    """Best achievable squared error for fixed decay parameters.

    Beta coefficients are solved via OLS; decay parameters are searched non-linearly.
    Args:
        lambdas: Decay parameters to condition on.
        tau: Maturities in years.
        yields: Observed zero rates aligned with ``tau``.

    Returns:
        Tuple ``(sum_of_squared_residuals, betas)``. The SSR is ``inf`` when the
        decay parameters are outside the admissible range.
    """
    if any(lam <= 0 for lam in lambdas):
        return float("inf"), np.zeros(len(lambdas) + 2)
    design = _curve_design(tau, lambdas)
    betas, *_ = np.linalg.lstsq(design, yields, rcond=None)
    residual = design @ betas - yields
    return float(residual @ residual), betas


def fit_yield_curve(
    maturities: Sequence[float] | np.ndarray,
    yields: Sequence[float] | np.ndarray,
    model: str = "svensson",
    decay_bounds: tuple[float, float] = CURVE_DECAY_BOUNDS,
    grid_points: int = CURVE_DECAY_GRID,
) -> CurveFit:
    """Fit a Nelson-Siegel or Svensson curve to observed zero rates.

    Beta coefficients are solved via OLS; decay parameters are searched over
    a geometric grid followed by Nelder-Mead simplex refinement.
    Args:
        maturities: Maturities in years, strictly positive.
        yields: Zero rates as decimals, aligned with ``maturities``.
        model: ``"nelson_siegel"`` or ``"svensson"``.
        decay_bounds: ``(low, high)`` search range in years for each decay
            parameter.
        grid_points: Grid resolution per decay parameter for the coarse pass.

    Returns:
        A :class:`CurveFit`, callable at arbitrary maturities.

    Raises:
        ValueError: If ``model`` is unknown, the inputs disagree in length, or
            there are fewer observations than free parameters.
    """
    if model not in ("nelson_siegel", "svensson"):
        raise ValueError(
            f"unknown model {model!r}; expected 'nelson_siegel' or 'svensson'"
        )
    tau = np.asarray(maturities, dtype=float)
    obs = np.asarray(yields, dtype=float)
    if tau.shape != obs.shape or tau.ndim != 1:
        raise ValueError("maturities and yields must be 1-D and the same length")
    if np.any(tau <= 0):
        raise ValueError("maturities must be strictly positive")

    n_decay = 1 if model == "nelson_siegel" else 2
    n_params = n_decay + 2 + n_decay  # betas + decay parameters
    if tau.size < n_params:
        raise ValueError(
            f"{model} has {n_params} parameters but only {tau.size} observations"
        )

    low, high = decay_bounds
    if not 0 < low < high:
        raise ValueError(f"decay_bounds must satisfy 0 < low < high, got {decay_bounds}")
    grid = np.geomspace(low, high, grid_points)

    best_ssr = float("inf")
    best_lambdas: tuple[float, ...] = (grid[0],) * n_decay
    if n_decay == 1:
        candidates = [(lam,) for lam in grid]
    else:
        # lambda1 == lambda2 makes the two curvature columns identical, so the
        # second hump carries no information; keep the pairs separated.
        candidates = [
            (short, long) for short in grid for long in grid if long > short * 1.05
        ]
    for lambdas in candidates:
        ssr, _ = _profiled_ssr(lambdas, tau, obs)
        if ssr < best_ssr:
            best_ssr, best_lambdas = ssr, lambdas

    def _opt_obj(log_p: np.ndarray) -> float:
        lams = np.exp(log_p)
        if n_decay == 2 and abs(lams[0] - lams[1]) < 1e-4:
            return float("inf")
        return _profiled_ssr(lams, tau, obs)[0]

    refined = minimize(
        _opt_obj,
        np.log(best_lambdas),
        method="Nelder-Mead",
        bounds=[(math.log(low), math.log(high))] * n_decay,
        options={"xatol": 1e-10, "fatol": 1e-18, "maxiter": 4000},
    )
    refined_lambdas = tuple(float(v) for v in np.exp(refined.x))
    refined_ssr, refined_betas = _profiled_ssr(refined_lambdas, tau, obs)
    if refined_ssr < best_ssr:
        best_ssr, best_lambdas = refined_ssr, refined_lambdas
        betas = refined_betas
    else:
        _, betas = _profiled_ssr(best_lambdas, tau, obs)

    params = tuple(float(b) for b in betas) + tuple(float(x) for x in best_lambdas)
    return CurveFit(
        model=model,
        params=params,
        rmse=float(np.sqrt(max(best_ssr, 0.0) / tau.size)),
    )
