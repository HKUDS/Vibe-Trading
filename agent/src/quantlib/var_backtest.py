"""VaR model backtesting: does the model's stated confidence level hold up?

``src.quantlib.risk`` *produces* VaR numbers. This module *validates* them, which
is a separate job with a separate consumer: a risk function has to demonstrate
that a 99% VaR was breached on roughly 1% of days, and that the breaches did not
arrive in clusters. A VaR that is right on average and wrong in bursts is the one
that ends a firm, because the losses land consecutively while the model still
reports a passing exception count.

Three tests, deliberately kept separate rather than collapsed into one verdict:

``kupiec_pof``
    Unconditional coverage. Are there the right *number* of breaches? Blind to
    when they happened -- a model breached ten days running and then never again
    passes this test.

``christoffersen_independence``
    Independence. Does a breach today predict a breach tomorrow? Blind to the
    level -- a model breached on 30% of days but evenly scattered passes this
    test.

``christoffersen_conditional_coverage``
    Both at once: ``LR_cc = LR_uc + LR_ind``, the sum being exact because the
    two restrictions are nested. Reported alongside its components, never
    instead of them, because a rejection tells you nothing about which half
    failed.

``basel_traffic_light`` is the supervisory overlay: the zone follows from the
cumulative binomial probability of the observed exception count, which is the
general form of the rule. The 1996 Basel scaling-factor table, by contrast, is
tabulated for a **250-day window at 99%** and is only reported when the sample
actually matches that; applying those multipliers to a 60-day sample would be a
category error dressed as a regulatory figure. See
:data:`BASEL_SCALING_FACTORS`.

WHAT COUNTS AS A BREACH
-----------------------
``return < -var``. The sign convention is inherited unchanged from
:mod:`src.quantlib.risk`: **a loss is a positive number**, so a 99% VaR of
``0.028`` means "a 2.8% loss", and a day returning ``-0.031`` breaches it while a
day returning ``-0.019`` does not. A VaR series that arrives negative is not
silently flipped -- see :func:`violation_indicator`.

ALIGNMENT IS NOT ASSUMED
------------------------
When both the returns and the VaR arrive as pandas Series, they are joined on
their index and any non-overlapping observation is an **error**, not a silent
drop. An off-by-one join between a return series and the VaR that was supposed
to have been forecast for it produces a plausible-looking exception count from
comparing each day against the wrong day's forecast, and nothing downstream can
detect it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.special import xlogy
from scipy.stats import binom, chi2

__all__ = [
    "BASEL_GREEN_MAX_CDF",
    "BASEL_RED_MIN_CDF",
    "BASEL_SCALING_FACTORS",
    "BASEL_WINDOW",
    "BASEL_CONFIDENCE",
    "ConditionalCoverageResult",
    "IndependenceResult",
    "KupiecResult",
    "TrafficLightResult",
    "VarBacktestReport",
    "violation_indicator",
    "kupiec_pof",
    "christoffersen_independence",
    "christoffersen_conditional_coverage",
    "basel_traffic_light",
    "var_backtest",
]

#: Cumulative binomial probability at or above which the Basel zone leaves green.
BASEL_GREEN_MAX_CDF: float = 0.95

#: Cumulative binomial probability at or above which the Basel zone becomes red.
BASEL_RED_MIN_CDF: float = 0.9999

#: Observation count the Basel scaling-factor table is tabulated for.
BASEL_WINDOW: int = 250

#: VaR confidence level the Basel scaling-factor table is tabulated for.
BASEL_CONFIDENCE: float = 0.99

#: Basel (1996) capital scaling factors by exception count, for a 250-day
#: backtest of a 99% VaR. Counts of 10 or more sit in the red zone at 4.00.
#: Keyed by exception count; only defined over the yellow zone and its
#: boundaries, because green is flat at 3.00 and red is flat at 4.00.
BASEL_SCALING_FACTORS: dict[int, float] = {
    0: 3.00, 1: 3.00, 2: 3.00, 3: 3.00, 4: 3.00,
    5: 3.40, 6: 3.50, 7: 3.65, 8: 3.75, 9: 3.85,
}

#: Scaling factor applied to every red-zone exception count.
BASEL_RED_SCALING_FACTOR: float = 4.00


@dataclass(frozen=True)
class KupiecResult:
    """Outcome of the Kupiec proportion-of-failures test.

    Attributes:
        observations: Number of paired observations tested.
        violations: Number of days the loss exceeded VaR.
        expected_violations: ``observations * (1 - confidence)``.
        violation_rate: Realised breach frequency, ``violations / observations``.
        expected_rate: ``1 - confidence``, the rate the model claims.
        statistic: Likelihood-ratio statistic ``LR_uc``, chi-square with 1 df.
        p_value: Probability of a statistic this large if the model is correct.
        rejected: True when ``p_value < significance``.
        significance: Significance level the rejection was judged at.
    """

    observations: int
    violations: int
    expected_violations: float
    violation_rate: float
    expected_rate: float
    statistic: float
    p_value: float
    rejected: bool
    significance: float


@dataclass(frozen=True)
class IndependenceResult:
    """Outcome of the Christoffersen independence test.

    Attributes:
        transitions: Counts ``(n00, n01, n10, n11)`` of consecutive state pairs,
            where state 1 is a breach day.
        prob_breach_after_calm: Estimated P(breach tomorrow | no breach today).
        prob_breach_after_breach: Estimated P(breach tomorrow | breach today).
        statistic: Likelihood-ratio statistic ``LR_ind``, chi-square with 1 df.
        p_value: Probability of a statistic this large under independence.
        rejected: True when ``p_value < significance``.
        significance: Significance level the rejection was judged at.
        identified: False when the sample cannot distinguish the two transition
            probabilities at all -- no breach occurred, or every breach sits at
            the very end of the sample. The statistic is then 0 by construction
            and the test carries no evidence either way.
    """

    transitions: tuple[int, int, int, int]
    prob_breach_after_calm: float
    prob_breach_after_breach: float
    statistic: float
    p_value: float
    rejected: bool
    significance: float
    identified: bool


@dataclass(frozen=True)
class ConditionalCoverageResult:
    """Outcome of the joint Christoffersen conditional-coverage test.

    Attributes:
        statistic: ``LR_cc = LR_uc + LR_ind``, chi-square with 2 df.
        p_value: Probability of a statistic this large if the model is correct.
        rejected: True when ``p_value < significance``.
        significance: Significance level the rejection was judged at.
        kupiec: The unconditional-coverage component.
        independence: The independence component.
    """

    statistic: float
    p_value: float
    rejected: bool
    significance: float
    kupiec: KupiecResult
    independence: IndependenceResult


@dataclass(frozen=True)
class TrafficLightResult:
    """Basel supervisory zone for an observed exception count.

    Attributes:
        zone: ``"green"``, ``"yellow"`` or ``"red"``.
        violations: Observed exception count.
        observations: Number of paired observations tested.
        cumulative_probability: ``P(X <= violations)`` under the model's own
            claimed breach probability. This is what the zone is cut on.
        scaling_factor: Basel capital multiplier, or None when the sample does
            not match the tabulated basis (see ``scaling_factor_basis``).
        scaling_factor_basis: Why ``scaling_factor`` is or is not populated.
    """

    zone: str
    violations: int
    observations: int
    cumulative_probability: float
    scaling_factor: float | None
    scaling_factor_basis: str


@dataclass(frozen=True)
class VarBacktestReport:
    """Every test in this module, run over one aligned return/VaR pair.

    Attributes:
        confidence: VaR confidence level tested.
        observations: Number of paired observations after alignment.
        violations: Number of breaches.
        dropped_observations: Pairs discarded because either side was non-finite.
        kupiec: Unconditional-coverage result.
        independence: Independence result.
        conditional_coverage: Joint result.
        traffic_light: Basel zone.
        breach_dates: Index labels of the breaches when the inputs carried an
            index, else None. A risk committee reads the dates, not the count.
    """

    confidence: float
    observations: int
    violations: int
    dropped_observations: int
    kupiec: KupiecResult
    independence: IndependenceResult
    conditional_coverage: ConditionalCoverageResult
    traffic_light: TrafficLightResult
    breach_dates: tuple[object, ...] | None


def _align(
    returns: pd.Series | np.ndarray | Sequence[float],
    var: pd.Series | np.ndarray | Sequence[float] | float,
) -> tuple[np.ndarray, np.ndarray, pd.Index | None, int]:
    """Pair each return with the VaR forecast that was made for it.

    Args:
        returns: Realised returns, signed (a loss is negative).
        var: VaR forecasts as positive loss magnitudes, either one per return or
            a single scalar applied to every return.

    Returns:
        Tuple of ``(returns, var, index, dropped)``: two equal-length finite
        float arrays, the surviving index when the inputs carried one, and the
        number of pairs dropped for holding a non-finite value.

    Raises:
        ValueError: If either input is not 1-D, if two indexed Series do not
            cover exactly the same labels, if the lengths differ, or if no
            finite pair survives.
    """
    ret_index = returns.index if isinstance(returns, pd.Series) else None
    var_index = var.index if isinstance(var, pd.Series) else None

    if ret_index is not None and var_index is not None:
        if not ret_index.equals(var_index):
            only_ret = ret_index.difference(var_index)
            only_var = var_index.difference(ret_index)
            raise ValueError(
                "returns and var must cover exactly the same labels; "
                f"{len(only_ret)} label(s) only in returns and "
                f"{len(only_var)} only in var. Align them explicitly -- a "
                "partial join silently compares each day against another day's "
                "forecast."
            )

    ret_values = np.asarray(returns, dtype=float)
    if ret_values.ndim > 1:
        raise ValueError(f"returns must be 1-D, got shape {ret_values.shape}")
    ret_values = ret_values.ravel()

    var_values = np.asarray(var, dtype=float)
    if var_values.ndim == 0:
        var_values = np.full(ret_values.shape, float(var_values))
    else:
        if var_values.ndim > 1:
            raise ValueError(f"var must be 1-D or scalar, got shape {var_values.shape}")
        var_values = var_values.ravel()

    if ret_values.size != var_values.size:
        raise ValueError(
            f"returns and var must be the same length, got {ret_values.size} "
            f"and {var_values.size}"
        )
    if ret_values.size == 0:
        raise ValueError("returns is empty")

    keep = np.isfinite(ret_values) & np.isfinite(var_values)
    dropped = int((~keep).sum())
    if not keep.any():
        raise ValueError("no observation has a finite return and a finite var")

    index = ret_index if ret_index is not None else var_index
    kept_index = index[keep] if index is not None else None
    return ret_values[keep], var_values[keep], kept_index, dropped


def violation_indicator(
    returns: pd.Series | np.ndarray | Sequence[float],
    var: pd.Series | np.ndarray | Sequence[float] | float,
) -> np.ndarray:
    """Flag the days on which the realised loss exceeded the VaR forecast.

    Args:
        returns: Realised returns, signed. A 3% loss is ``-0.03``.
        var: VaR forecasts as positive loss magnitudes, one per return or a
            single scalar. A negative entry is not flipped: it is taken at face
            value, meaning "the model expects a gain even in the tail", which is
            almost always a caller-side sign error and shows up here as an
            implausible breach count rather than as a silently corrected input.

    Returns:
        Boolean array, True where ``return < -var``. Equality is not a breach:
        a loss exactly equal to VaR is the level the model promised, not an
        excess of it.

    Raises:
        ValueError: If the inputs cannot be aligned (see :func:`_align`).
    """
    ret_values, var_values, _, _ = _align(returns, var)
    return ret_values < -var_values


def kupiec_pof(
    violations: int,
    observations: int,
    confidence: float = 0.99,
    significance: float = 0.05,
) -> KupiecResult:
    """Test whether the breach *count* matches the model's claimed level.

    The Kupiec proportion-of-failures test compares the realised breach rate
    against ``1 - confidence`` by likelihood ratio::

        LR_uc = -2 * [ (n-x)*ln(1-p) + x*ln(p)
                       - (n-x)*ln(1-x/n) - x*ln(x/n) ]

    distributed chi-square with 1 degree of freedom. The ``0 * ln(0) = 0``
    convention makes the zero-breach and all-breach cases well defined rather
    than special.

    Args:
        violations: Number of days the loss exceeded VaR.
        observations: Number of days tested.
        confidence: VaR confidence level the model claims, e.g. 0.99.
        significance: Level at which ``rejected`` is decided.

    Returns:
        A :class:`KupiecResult`.

    Raises:
        ValueError: If ``observations`` is not positive, if ``violations`` is
            negative or exceeds ``observations``, or if either probability is
            not strictly between 0 and 1.
    """
    if observations <= 0:
        raise ValueError(f"observations must be > 0, got {observations}")
    if not 0 <= violations <= observations:
        raise ValueError(
            f"violations must be in [0, {observations}], got {violations}"
        )
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if not 0.0 < significance < 1.0:
        raise ValueError(f"significance must be in (0, 1), got {significance}")

    expected_rate = 1.0 - confidence
    observed_rate = violations / observations
    calm = observations - violations

    restricted = xlogy(calm, 1.0 - expected_rate) + xlogy(violations, expected_rate)
    unrestricted = xlogy(calm, 1.0 - observed_rate) + xlogy(violations, observed_rate)
    statistic = float(max(-2.0 * (restricted - unrestricted), 0.0))
    p_value = float(chi2.sf(statistic, df=1))

    return KupiecResult(
        observations=observations,
        violations=violations,
        expected_violations=observations * expected_rate,
        violation_rate=observed_rate,
        expected_rate=expected_rate,
        statistic=statistic,
        p_value=p_value,
        rejected=p_value < significance,
        significance=significance,
    )


def christoffersen_independence(
    breaches: Sequence[bool] | np.ndarray,
    significance: float = 0.05,
) -> IndependenceResult:
    """Test whether breaches cluster in time.

    Fits a first-order Markov chain to the breach sequence and tests the
    restriction that the two transition probabilities are equal::

        LR_ind = -2 * [ (n00+n10)*ln(1-pi) + (n01+n11)*ln(pi)
                        - n00*ln(1-pi01) - n01*ln(pi01)
                        - n10*ln(1-pi11) - n11*ln(pi11) ]

    distributed chi-square with 1 degree of freedom. This is the test that
    catches a model whose exception count looks fine because all ten breaches
    landed in the same fortnight.

    Args:
        breaches: Boolean sequence in chronological order, True on breach days.
        significance: Level at which ``rejected`` is decided.

    Returns:
        An :class:`IndependenceResult`. When the sample holds no breach, or
        holds breaches only in its final position, the transition probabilities
        are not separately identified; the statistic is then 0 with
        ``identified=False`` rather than an arbitrary number.

    Raises:
        ValueError: If ``breaches`` holds fewer than two observations or is not
            1-D, or if ``significance`` is not strictly between 0 and 1.
    """
    if not 0.0 < significance < 1.0:
        raise ValueError(f"significance must be in (0, 1), got {significance}")

    flags = np.asarray(breaches)
    if flags.ndim != 1:
        raise ValueError(f"breaches must be 1-D, got shape {flags.shape}")
    if flags.size < 2:
        raise ValueError(
            f"breaches needs at least 2 observations to hold a transition, got {flags.size}"
        )
    flags = flags.astype(bool)

    prev, curr = flags[:-1], flags[1:]
    n00 = int(np.sum(~prev & ~curr))
    n01 = int(np.sum(~prev & curr))
    n10 = int(np.sum(prev & ~curr))
    n11 = int(np.sum(prev & curr))

    from_calm = n00 + n01
    from_breach = n10 + n11
    total = from_calm + from_breach

    pi01 = n01 / from_calm if from_calm else 0.0
    pi11 = n11 / from_breach if from_breach else 0.0
    pi = (n01 + n11) / total if total else 0.0

    # Not identified when no day follows a breach: pi11 has no sample behind it,
    # so the restriction it is supposed to relax cannot be tested.
    identified = from_breach > 0 and from_calm > 0

    if not identified:
        statistic = 0.0
    else:
        restricted = xlogy(n00 + n10, 1.0 - pi) + xlogy(n01 + n11, pi)
        unrestricted = (
            xlogy(n00, 1.0 - pi01)
            + xlogy(n01, pi01)
            + xlogy(n10, 1.0 - pi11)
            + xlogy(n11, pi11)
        )
        statistic = float(max(-2.0 * (restricted - unrestricted), 0.0))

    p_value = float(chi2.sf(statistic, df=1))
    return IndependenceResult(
        transitions=(n00, n01, n10, n11),
        prob_breach_after_calm=pi01,
        prob_breach_after_breach=pi11,
        statistic=statistic,
        p_value=p_value,
        rejected=identified and p_value < significance,
        significance=significance,
        identified=identified,
    )


def christoffersen_conditional_coverage(
    breaches: Sequence[bool] | np.ndarray,
    confidence: float = 0.99,
    significance: float = 0.05,
) -> ConditionalCoverageResult:
    """Test coverage and independence jointly.

    ``LR_cc = LR_uc + LR_ind`` with 2 degrees of freedom. The components are
    returned alongside it because the joint statistic alone cannot say whether
    the model failed on level, on timing, or on both -- and the remedies differ.

    Args:
        breaches: Boolean sequence in chronological order, True on breach days.
        confidence: VaR confidence level the model claims.
        significance: Level at which each ``rejected`` flag is decided.

    Returns:
        A :class:`ConditionalCoverageResult`.

    Raises:
        ValueError: Propagated from the component tests.
    """
    flags = np.asarray(breaches)
    if flags.ndim != 1:
        raise ValueError(f"breaches must be 1-D, got shape {flags.shape}")
    flags = flags.astype(bool)

    kupiec = kupiec_pof(
        violations=int(flags.sum()),
        observations=int(flags.size),
        confidence=confidence,
        significance=significance,
    )
    independence = christoffersen_independence(flags, significance=significance)

    statistic = kupiec.statistic + independence.statistic
    p_value = float(chi2.sf(statistic, df=2))
    return ConditionalCoverageResult(
        statistic=statistic,
        p_value=p_value,
        rejected=p_value < significance,
        significance=significance,
        kupiec=kupiec,
        independence=independence,
    )


def basel_traffic_light(
    violations: int,
    observations: int,
    confidence: float = BASEL_CONFIDENCE,
) -> TrafficLightResult:
    """Place an exception count in the Basel supervisory zone.

    The zone is cut on the cumulative binomial probability of the observed
    count under the model's own claimed breach probability -- green below
    :data:`BASEL_GREEN_MAX_CDF`, red at or above :data:`BASEL_RED_MIN_CDF`,
    yellow between. That is the general form of the rule and it holds for any
    sample size.

    The capital scaling factor is a different matter. :data:`BASEL_SCALING_FACTORS`
    is tabulated for a 250-day backtest of a 99% VaR, and is reported only when
    the sample matches that basis. On any other sample the zone is still
    meaningful but the multiplier is not, so it comes back None rather than
    borrowed from a table that was never fitted to it.

    Args:
        violations: Observed exception count.
        observations: Number of days tested.
        confidence: VaR confidence level the model claims.

    Returns:
        A :class:`TrafficLightResult`.

    Raises:
        ValueError: If ``observations`` is not positive, if ``violations`` is
            outside ``[0, observations]``, or if ``confidence`` is not strictly
            between 0 and 1.
    """
    if observations <= 0:
        raise ValueError(f"observations must be > 0, got {observations}")
    if not 0 <= violations <= observations:
        raise ValueError(
            f"violations must be in [0, {observations}], got {violations}"
        )
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")

    breach_prob = 1.0 - confidence
    cdf = float(binom.cdf(violations, observations, breach_prob))

    if cdf < BASEL_GREEN_MAX_CDF:
        zone = "green"
    elif cdf < BASEL_RED_MIN_CDF:
        zone = "yellow"
    else:
        zone = "red"

    on_basis = observations == BASEL_WINDOW and confidence == BASEL_CONFIDENCE
    if not on_basis:
        scaling_factor = None
        basis = (
            f"not reported: the Basel table is tabulated for {BASEL_WINDOW} "
            f"observations at {BASEL_CONFIDENCE:.0%} confidence, this sample is "
            f"{observations} at {confidence:.0%}"
        )
    else:
        scaling_factor = BASEL_SCALING_FACTORS.get(violations, BASEL_RED_SCALING_FACTOR)
        basis = (
            f"Basel (1996) table for {BASEL_WINDOW} observations at "
            f"{BASEL_CONFIDENCE:.0%} confidence"
        )

    return TrafficLightResult(
        zone=zone,
        violations=violations,
        observations=observations,
        cumulative_probability=cdf,
        scaling_factor=scaling_factor,
        scaling_factor_basis=basis,
    )


def var_backtest(
    returns: pd.Series | np.ndarray | Sequence[float],
    var: pd.Series | np.ndarray | Sequence[float] | float,
    confidence: float = 0.99,
    significance: float = 0.05,
) -> VarBacktestReport:
    """Run every test in this module over one return/VaR pair.

    Args:
        returns: Realised returns, signed, in chronological order.
        var: VaR forecasts as positive loss magnitudes -- one per return, or a
            scalar for a constant-VaR model. When both sides are indexed Series
            the labels must match exactly.
        confidence: VaR confidence level the model claims, e.g. 0.99.
        significance: Level at which each ``rejected`` flag is decided.

    Returns:
        A :class:`VarBacktestReport` carrying the Kupiec, independence, joint
        and Basel results plus the breach dates when an index was supplied.

    Raises:
        ValueError: If the inputs cannot be aligned, if fewer than two finite
            pairs survive, or if either probability is out of range.
    """
    ret_values, var_values, index, dropped = _align(returns, var)
    if ret_values.size < 2:
        raise ValueError(
            f"var_backtest needs at least 2 aligned observations, got {ret_values.size}"
        )

    breaches = ret_values < -var_values
    conditional = christoffersen_conditional_coverage(
        breaches, confidence=confidence, significance=significance
    )
    traffic = basel_traffic_light(
        violations=int(breaches.sum()),
        observations=int(breaches.size),
        confidence=confidence,
    )
    breach_dates = tuple(index[breaches]) if index is not None else None

    return VarBacktestReport(
        confidence=confidence,
        observations=int(breaches.size),
        violations=int(breaches.sum()),
        dropped_observations=dropped,
        kupiec=conditional.kupiec,
        independence=conditional.independence,
        conditional_coverage=conditional,
        traffic_light=traffic,
        breach_dates=breach_dates,
    )
