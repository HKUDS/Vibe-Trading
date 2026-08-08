"""Multiple-testing control: how much of a backtest's edge is search luck?

Run 462 factors over one history, keep the best Sharpe, and you have not
measured an edge -- you have measured the maximum of 462 draws. Under a null
where every factor is worthless, that maximum is comfortably positive, and it
grows with how many you tried. Reporting it without saying how many were tried
is the single most common way a research process fools itself.

This module supplies the three corrections, in increasing order of what they
demand of the caller:

``probabilistic_sharpe_ratio``
    The confidence that one strategy's true Sharpe exceeds a benchmark, given
    the sample length and the return distribution's skew and kurtosis. No trial
    count involved. This is the building block.

``deflated_sharpe_ratio``
    The same statement, but with the benchmark raised to the Sharpe you would
    expect the *best of N trials* to reach by luck alone. Needs the number of
    trials and the dispersion of their Sharpes. This is the number to publish
    beside any "best factor" claim.

``probability_of_backtest_overfitting``
    CSCV. Needs the full return matrix of every trial, not just summary
    statistics, and answers a different question: across many in-sample /
    out-of-sample splits, how often does the in-sample winner land below the
    out-of-sample median? A PBO above 0.5 means the selection procedure itself
    is anti-predictive.

``benjamini_hochberg``
    When the question is "which of these N are real" rather than "is the best
    one real", control the false discovery rate instead of deflating a maximum.

TWO CONVENTIONS THAT SILENTLY BREAK THESE FORMULAS
--------------------------------------------------
**Sharpe must be per-observation, not annualised.** Every formula here pairs the
Sharpe with the observation count ``T``. Feeding an annualised Sharpe with a
daily ``T`` inflates the statistic by roughly sqrt(252) and turns a coin flip
into a certainty. :func:`probabilistic_sharpe_ratio` cannot detect this, so it
is stated here and repeated in each docstring.

**Kurtosis is non-excess.** The Bailey-Lopez de Prado derivation uses the fourth
standardised moment, which is **3** for a Gaussian, not 0. ``scipy.stats.kurtosis``
returns the *excess* form by default and ``pandas.Series.kurt`` likewise. Passing
excess kurtosis makes the variance term ``1 - skew*SR + (gamma4-1)/4 * SR^2``
too small and the resulting confidence too high. :data:`GAUSSIAN_KURTOSIS` is
provided as the default so the common case is right without thinking about it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
from scipy.stats import norm

__all__ = [
    "DEFAULT_CSCV_SPLITS",
    "EULER_MASCHERONI",
    "GAUSSIAN_KURTOSIS",
    "MIN_OBSERVATIONS",
    "CSCVResult",
    "DeflatedSharpeResult",
    "FDRResult",
    "benjamini_hochberg",
    "deflated_sharpe_ratio",
    "expected_maximum_sharpe",
    "probabilistic_sharpe_ratio",
    "probability_of_backtest_overfitting",
    "sharpe_ratio",
]

#: Euler-Mascheroni constant, from the expected-maximum-of-N-Gaussians result.
EULER_MASCHERONI: float = 0.5772156649015329

#: Fourth standardised moment of a Gaussian. NOT zero -- see the module
#: docstring. The default wherever a kurtosis argument is optional.
GAUSSIAN_KURTOSIS: float = 3.0

#: Subsets the CSCV procedure splits the sample into. Must be even; 16 gives
#: C(16,8) = 12,870 splits, which is the published choice and runs in seconds.
DEFAULT_CSCV_SPLITS: int = 16

#: Fewest return observations for which these statistics mean anything. The
#: ``sqrt(T - 1)`` scaling is not the binding constraint -- the skew and
#: kurtosis estimates are, and they are hopeless on a short sample.
MIN_OBSERVATIONS: int = 30


@dataclass(frozen=True)
class DeflatedSharpeResult:
    """Outcome of deflating an observed Sharpe for the number of trials.

    Attributes:
        observed_sharpe: The Sharpe that was actually observed, per-observation.
        expected_maximum_sharpe: The Sharpe the best of ``n_trials`` would be
            expected to reach under a null where none of them has any edge.
            This is the bar the observed Sharpe has to clear.
        deflated_sharpe_ratio: Probability in ``[0, 1]`` that the true Sharpe
            exceeds ``expected_maximum_sharpe``. Read it as a confidence: 0.95
            means the result survives the search correction at 95%.
        n_trials: How many strategies were searched over.
        n_observations: Length of the return sample.
        trial_sharpe_std: Dispersion of the trial Sharpes that set the bar.
        skew: Return skewness used.
        kurtosis: Non-excess kurtosis used.
        survives: True when ``deflated_sharpe_ratio`` exceeds ``confidence``.
        confidence: Threshold ``survives`` was judged at.
    """

    observed_sharpe: float
    expected_maximum_sharpe: float
    deflated_sharpe_ratio: float
    n_trials: int
    n_observations: int
    trial_sharpe_std: float
    skew: float
    kurtosis: float
    survives: bool
    confidence: float


@dataclass(frozen=True)
class FDRResult:
    """Benjamini-Hochberg false-discovery-rate control over many hypotheses.

    Attributes:
        rejected: Boolean array, True where the null is rejected.
        adjusted_p_values: BH-adjusted p-values, monotone non-decreasing in the
            sorted order and clipped at 1.
        n_rejected: Count of rejections.
        threshold: Largest raw p-value that was rejected, or 0.0 if none were.
        fdr: The false-discovery rate the procedure controlled at.
    """

    rejected: np.ndarray
    adjusted_p_values: np.ndarray
    n_rejected: int
    threshold: float
    fdr: float


@dataclass(frozen=True)
class CSCVResult:
    """Combinatorially-symmetric cross-validation overfitting diagnostic.

    Attributes:
        pbo: Probability of backtest overfitting -- the fraction of splits in
            which the in-sample best strategy landed below the out-of-sample
            median. Above 0.5 the selection rule is worse than picking at random.
        logits: Logit of the out-of-sample relative rank, one per split.
        n_splits: Number of in-sample/out-of-sample combinations evaluated.
        n_strategies: Strategies compared.
        n_observations: Rows actually used.
        dropped_observations: Rows trimmed from the end so the sample divides
            evenly into subsets. Reported, never silent.
        in_sample_sharpes: In-sample Sharpe of the selected strategy per split.
        out_of_sample_sharpes: Out-of-sample Sharpe of that same strategy.
        performance_degradation: Slope of out-of-sample on in-sample Sharpe
            across splits. A negative slope means better in-sample selection
            produced worse out-of-sample results, which is overfitting in its
            purest observable form.
    """

    pbo: float
    logits: np.ndarray
    n_splits: int
    n_strategies: int
    n_observations: int
    dropped_observations: int
    in_sample_sharpes: np.ndarray
    out_of_sample_sharpes: np.ndarray
    performance_degradation: float


def sharpe_ratio(
    returns: pd.Series | np.ndarray | Sequence[float],
    risk_free: float = 0.0,
    ddof: int = 1,
) -> float:
    """Per-observation Sharpe ratio.

    Deliberately NOT annualised: every other function in this module pairs the
    Sharpe with an observation count, and mixing an annualised numerator with a
    per-period count is the error the module docstring warns about.

    Args:
        returns: Return observations.
        risk_free: Risk-free rate per observation, in the same units.
        ddof: Delta degrees of freedom for the standard deviation. Defaults to 1
            to match ``src.quantlib.timeseries.bootstrap_sharpe``; pass 0 to
            match a population-convention implementation. The two differ by
            ``sqrt(T/(T-1))``, which is immaterial at T=1000 and is not at T=30.

    Returns:
        ``mean(excess) / std(excess)``, or ``nan`` when the excess returns have
        no dispersion.

    Raises:
        ValueError: If fewer than two finite observations are supplied.
    """
    values = np.asarray(returns, dtype=float).ravel()
    values = values[np.isfinite(values)]
    if values.size < 2:
        raise ValueError(f"sharpe_ratio needs at least 2 observations, got {values.size}")
    excess = values - risk_free
    spread = float(excess.std(ddof=ddof))
    if not np.isfinite(spread) or spread <= 0.0:
        return float("nan")
    return float(excess.mean() / spread)


def probabilistic_sharpe_ratio(
    observed_sharpe: float,
    n_observations: int,
    benchmark_sharpe: float = 0.0,
    skew: float = 0.0,
    kurtosis: float = GAUSSIAN_KURTOSIS,
) -> float:
    """Confidence that a strategy's true Sharpe exceeds a benchmark.

    ``PSR = Z[ (SR - SR*) * sqrt(T - 1) / sqrt(1 - g3*SR + (g4 - 1)/4 * SR^2) ]``

    The denominator is why this is not just a t-test: negative skew and fat
    tails both make a given Sharpe less trustworthy, and both are routine in
    strategy returns.

    Args:
        observed_sharpe: Observed Sharpe, **per-observation** and matched to
            ``n_observations``. An annualised Sharpe here inflates the result.
        n_observations: Number of return observations behind the Sharpe.
        benchmark_sharpe: Sharpe to beat, per-observation. Zero asks "is this
            better than nothing"; :func:`deflated_sharpe_ratio` raises it to the
            expected best-of-N instead.
        skew: Third standardised moment of the returns.
        kurtosis: Fourth standardised moment, **non-excess** (3 for Gaussian).

    Returns:
        Probability in ``[0, 1]``.

    Raises:
        ValueError: If ``n_observations`` is below :data:`MIN_OBSERVATIONS`, if
            ``kurtosis`` is below 1 (impossible for any distribution), or if the
            variance term is non-positive, which means the supplied moments are
            mutually inconsistent rather than merely extreme.
    """
    if n_observations < MIN_OBSERVATIONS:
        raise ValueError(
            f"need at least {MIN_OBSERVATIONS} observations, got {n_observations}"
        )
    if kurtosis < 1.0:
        raise ValueError(
            f"kurtosis must be the non-excess fourth moment (>= 1, 3 for a "
            f"Gaussian), got {kurtosis}. Excess kurtosis was probably passed."
        )
    if not np.isfinite(observed_sharpe):
        raise ValueError(f"observed_sharpe must be finite, got {observed_sharpe}")

    variance_term = (
        1.0 - skew * observed_sharpe + (kurtosis - 1.0) / 4.0 * observed_sharpe**2
    )
    if variance_term <= 0.0:
        raise ValueError(
            f"the Sharpe variance term is {variance_term:.4f}, which is not "
            "positive; the supplied skew and kurtosis are mutually inconsistent "
            "with this Sharpe"
        )

    statistic = (
        (observed_sharpe - benchmark_sharpe)
        * math.sqrt(n_observations - 1)
        / math.sqrt(variance_term)
    )
    return float(norm.cdf(statistic))


def expected_maximum_sharpe(n_trials: int, trial_sharpe_std: float) -> float:
    """Sharpe the best of ``n_trials`` reaches by luck alone.

    From the expected maximum of ``N`` independent Gaussians::

        E[max] ~ std * [ (1 - g) * Z^-1(1 - 1/N) + g * Z^-1(1 - 1/(N*e)) ]

    with ``g`` the Euler-Mascheroni constant. This is the bar an observed Sharpe
    has to clear before "we tried 462 factors and this was the best" says
    anything at all.

    Args:
        n_trials: Number of strategies searched over. Must be at least 2 -- with
            one trial there is no maximum to correct for and the answer is 0.
        trial_sharpe_std: Standard deviation of the Sharpes across those trials,
            per-observation.

    Returns:
        The expected maximum Sharpe under the null, per-observation. Zero when
        ``trial_sharpe_std`` is zero.

    Raises:
        ValueError: If ``n_trials`` is below 1 or ``trial_sharpe_std`` is
            negative.
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be at least 1, got {n_trials}")
    if trial_sharpe_std < 0.0:
        raise ValueError(f"trial_sharpe_std must be >= 0, got {trial_sharpe_std}")
    if n_trials == 1 or trial_sharpe_std == 0.0:
        return 0.0

    quantile_a = norm.ppf(1.0 - 1.0 / n_trials)
    quantile_b = norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    return float(
        trial_sharpe_std
        * ((1.0 - EULER_MASCHERONI) * quantile_a + EULER_MASCHERONI * quantile_b)
    )


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    n_observations: int,
    trial_sharpe_std: float,
    skew: float = 0.0,
    kurtosis: float = GAUSSIAN_KURTOSIS,
    confidence: float = 0.95,
) -> DeflatedSharpeResult:
    """Deflate an observed Sharpe by the number of strategies searched.

    Args:
        observed_sharpe: Best observed Sharpe, per-observation.
        n_trials: How many strategies were searched. This is the number a
            research process usually fails to record; without it no correction
            is possible and the reported Sharpe is not interpretable.
        n_observations: Length of the return sample.
        trial_sharpe_std: Standard deviation of the Sharpes across the trials.
        skew: Third standardised moment of the winning strategy's returns.
        kurtosis: Fourth standardised moment, non-excess.
        confidence: Level at which ``survives`` is decided.

    Returns:
        A :class:`DeflatedSharpeResult`.

    Raises:
        ValueError: Propagated from :func:`expected_maximum_sharpe` and
            :func:`probabilistic_sharpe_ratio`.
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")

    bar = expected_maximum_sharpe(n_trials, trial_sharpe_std)
    dsr = probabilistic_sharpe_ratio(
        observed_sharpe=observed_sharpe,
        n_observations=n_observations,
        benchmark_sharpe=bar,
        skew=skew,
        kurtosis=kurtosis,
    )
    return DeflatedSharpeResult(
        observed_sharpe=observed_sharpe,
        expected_maximum_sharpe=bar,
        deflated_sharpe_ratio=dsr,
        n_trials=n_trials,
        n_observations=n_observations,
        trial_sharpe_std=trial_sharpe_std,
        skew=skew,
        kurtosis=kurtosis,
        survives=dsr > confidence,
        confidence=confidence,
    )


def benjamini_hochberg(
    p_values: Sequence[float] | np.ndarray,
    fdr: float = 0.05,
) -> FDRResult:
    """Control the false discovery rate across many simultaneous tests.

    Bonferroni controls the probability of *any* false positive and is far too
    strict when hundreds of factors are screened; BH instead bounds the expected
    *fraction* of rejections that are false, which is the quantity a research
    pipeline actually cares about.

    Args:
        p_values: Raw p-values, one per hypothesis. Must all lie in ``[0, 1]``.
        fdr: False discovery rate to control at.

    Returns:
        An :class:`FDRResult` whose ``rejected`` and ``adjusted_p_values`` are in
        the caller's original order.

    Raises:
        ValueError: If ``p_values`` is empty, holds a value outside ``[0, 1]``
            or a non-finite value, or if ``fdr`` is not in ``(0, 1)``.
    """
    if not 0.0 < fdr < 1.0:
        raise ValueError(f"fdr must be in (0, 1), got {fdr}")

    values = np.asarray(p_values, dtype=float).ravel()
    if values.size == 0:
        raise ValueError("p_values is empty")
    if not np.isfinite(values).all():
        raise ValueError("p_values holds a non-finite value")
    if ((values < 0.0) | (values > 1.0)).any():
        raise ValueError("every p-value must lie in [0, 1]")

    n = values.size
    order = np.argsort(values, kind="stable")
    sorted_p = values[order]
    ranks = np.arange(1, n + 1)

    # Step-up: the largest rank whose p-value clears its own threshold, and
    # everything below it, is rejected.
    below = sorted_p <= (ranks / n) * fdr
    if below.any():
        cutoff_rank = int(ranks[below].max())
        threshold = float(sorted_p[cutoff_rank - 1])
    else:
        cutoff_rank = 0
        threshold = 0.0

    rejected_sorted = ranks <= cutoff_rank

    # Adjusted p-values are the running minimum from the largest rank down, so
    # they cannot decrease as the raw p-value increases.
    adjusted_sorted = np.minimum.accumulate((n / ranks * sorted_p)[::-1])[::-1]
    adjusted_sorted = np.clip(adjusted_sorted, 0.0, 1.0)

    rejected = np.empty(n, dtype=bool)
    adjusted = np.empty(n, dtype=float)
    rejected[order] = rejected_sorted
    adjusted[order] = adjusted_sorted

    return FDRResult(
        rejected=rejected,
        adjusted_p_values=adjusted,
        n_rejected=int(rejected.sum()),
        threshold=threshold,
        fdr=fdr,
    )


def probability_of_backtest_overfitting(
    performance: pd.DataFrame | np.ndarray,
    n_splits: int = DEFAULT_CSCV_SPLITS,
    ddof: int = 1,
) -> CSCVResult:
    """Combinatorially-symmetric cross-validation (CSCV) overfitting diagnostic.

    Splits the sample into ``n_splits`` contiguous subsets, then for every way of
    choosing half of them as in-sample, picks the strategy with the best
    in-sample Sharpe and records where it ranks out-of-sample. If selection
    carried information, the in-sample winner would tend to rank high
    out-of-sample; if the process is fitting noise, it lands anywhere, and below
    the median about half the time.

    Args:
        performance: Returns per strategy, rows as observations and columns as
            strategies. A DataFrame's column labels are preserved only for the
            caller's convenience; this function returns no per-strategy output.
        n_splits: Number of subsets. Must be even and at least 4; the number of
            combinations is ``C(n_splits, n_splits/2)``, so 16 gives 12,870.
        ddof: Delta degrees of freedom for the Sharpe standard deviation,
            forwarded to :func:`sharpe_ratio`.

    Returns:
        A :class:`CSCVResult`.

    Raises:
        ValueError: If ``n_splits`` is odd or below 4, if fewer than 2
            strategies are supplied (a rank needs competitors), if the sample
            cannot give each subset at least 2 rows, or if every strategy has
            zero variance so no Sharpe is defined.
    """
    if n_splits < 4 or n_splits % 2 != 0:
        raise ValueError(f"n_splits must be an even number >= 4, got {n_splits}")

    frame = pd.DataFrame(performance)
    matrix = frame.to_numpy(dtype=float)
    if matrix.ndim != 2:
        raise ValueError(f"performance must be 2-D, got shape {matrix.shape}")

    n_rows, n_strategies = matrix.shape
    if n_strategies < 2:
        raise ValueError(
            f"CSCV ranks strategies against each other and needs at least 2, "
            f"got {n_strategies}"
        )

    subset_size = n_rows // n_splits
    if subset_size < 2:
        raise ValueError(
            f"{n_rows} rows split {n_splits} ways gives {subset_size} row(s) per "
            "subset; each subset needs at least 2 for a Sharpe"
        )

    used_rows = subset_size * n_splits
    dropped = n_rows - used_rows
    trimmed = matrix[:used_rows]
    subsets = [
        trimmed[i * subset_size : (i + 1) * subset_size] for i in range(n_splits)
    ]

    logits: list[float] = []
    in_sample_sharpes: list[float] = []
    out_sample_sharpes: list[float] = []
    all_indices = set(range(n_splits))

    for chosen in combinations(range(n_splits), n_splits // 2):
        rest = sorted(all_indices - set(chosen))
        in_sample = np.vstack([subsets[i] for i in chosen])
        out_sample = np.vstack([subsets[i] for i in rest])

        in_scores = np.array(
            [sharpe_ratio(in_sample[:, j], ddof=ddof) for j in range(n_strategies)]
        )
        if not np.isfinite(in_scores).any():
            continue
        best = int(np.nanargmax(np.where(np.isfinite(in_scores), in_scores, -np.inf)))

        out_scores = np.array(
            [sharpe_ratio(out_sample[:, j], ddof=ddof) for j in range(n_strategies)]
        )
        finite_out = np.isfinite(out_scores)
        if not finite_out[best] or finite_out.sum() < 2:
            continue

        # Relative rank of the selected strategy among all strategies OOS, on
        # (0, 1). Ties are resolved by average rank so a plateau does not push
        # the logit to an endpoint.
        ranked = pd.Series(np.where(finite_out, out_scores, np.nan)).rank(
            method="average"
        )
        omega = float(ranked.iloc[best] / (finite_out.sum() + 1))
        omega = min(max(omega, 1e-12), 1.0 - 1e-12)

        logits.append(math.log(omega / (1.0 - omega)))
        in_sample_sharpes.append(float(in_scores[best]))
        out_sample_sharpes.append(float(out_scores[best]))

    if not logits:
        raise ValueError(
            "no split produced a usable Sharpe; every strategy may have zero "
            "variance within the subsets"
        )

    logit_array = np.array(logits)
    in_array = np.array(in_sample_sharpes)
    out_array = np.array(out_sample_sharpes)

    if in_array.size >= 2 and float(in_array.std()) > 0:
        degradation = float(np.polyfit(in_array, out_array, 1)[0])
    else:
        degradation = float("nan")

    return CSCVResult(
        pbo=float((logit_array <= 0).mean()),
        logits=logit_array,
        n_splits=len(logits),
        n_strategies=n_strategies,
        n_observations=used_rows,
        dropped_observations=dropped,
        in_sample_sharpes=in_array,
        out_of_sample_sharpes=out_array,
        performance_degradation=degradation,
    )
