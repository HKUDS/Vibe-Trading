"""Cross-sectional style factor model: exposures, factor returns, drift.

This is the machinery behind "what is this portfolio actually betting on" --
whether a fund's outperformance came from a persistent tilt toward small, cheap,
high-momentum names, or from something the tilts do not explain.

IT IS NOT BARRA
---------------
Barra is a licensed commercial product from MSCI: their factor definitions,
their estimation universe, their covariance matrix. None of that is here and
none of it can be reproduced from public data. What is here is a
*Barra-style* cross-sectional model built from definitions stated in
:data:`STYLE_FACTOR_DEFINITIONS`, which are public-domain academic
constructions. Report the output as a style exposure from a named model. Never
present a number from this module as a Barra exposure -- they will not agree,
because they are not measuring the same thing.

THE STANDARDISATION IS THE MODEL
--------------------------------
An exposure is a cross-sectional z-score, so "value = 1.2" means *1.2 standard
deviations cheaper than the universe on this date*, not any absolute cheapness.
Three details make that number mean what it claims:

1. **Winsorise before standardising.** One delisting-bound name with a book/price
   of 40 will otherwise move the mean and inflate the standard deviation enough
   to compress every other name toward zero.
2. **Cap-weighted mean, equal-weighted standard deviation.** The mean is
   cap-weighted so that the *market portfolio* has zero exposure by construction
   -- which is what makes a portfolio's exposure readable as an active tilt away
   from the market rather than a level. The standard deviation is equal-weighted
   so a handful of megacaps cannot set the scale for the whole cross-section.
   This asymmetry is deliberate and is the convention commercial risk models use.
3. **A missing characteristic becomes exposure zero, i.e. the market average**,
   and the count of filled cells is reported. Dropping the name instead would
   silently change the universe between factors; imputing a nonzero value would
   invent a tilt.

FACTOR RETURNS COME FROM A CROSS-SECTIONAL REGRESSION
-----------------------------------------------------
For each date, regress that date's asset returns on the previous date's
exposures. The coefficients are the factor returns: what one unit of exposure
paid on that day. Weighting by square-root market cap is the standard choice --
it treats the regression as heteroskedastic in the way small caps actually are,
without letting megacaps dominate as full-cap weighting would.

The intercept is the market factor. It must be present: dropping it forces every
factor to absorb the market's return, and the "value factor" then reports the
market's direction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "DEFAULT_WINSORISE",
    "MARKET_FACTOR",
    "MIN_CROSS_SECTION",
    "STYLE_FACTOR_DEFINITIONS",
    "FactorReturnFit",
    "StyleDrift",
    "standardise_exposures",
    "build_style_exposures",
    "cross_sectional_factor_returns",
    "portfolio_style_exposure",
    "style_drift",
    "factor_return_attribution",
]

#: Fraction trimmed from each tail before standardising.
DEFAULT_WINSORISE: float = 0.025

#: Name of the regression intercept, which is the market factor.
MARKET_FACTOR: str = "market"

#: Fewest assets a cross-section needs before a z-score or a regression on it
#: means anything. Below this the standard deviation is noise.
MIN_CROSS_SECTION: int = 10

#: Style factors and the raw characteristics each is built from.
#:
#: Each entry maps a factor name to ``{characteristic: sign}``. The
#: characteristic names are what :func:`build_style_exposures` expects as
#: columns; ``sign`` is ``+1`` when a larger raw value means a larger exposure
#: and ``-1`` when it means a smaller one. Every characteristic is standardised
#: on its own before the signed average, so factors built from several inputs
#: are not dominated by whichever input happens to have the widest spread.
#:
#: These are public academic definitions, restated here so that a reader can
#: check what a reported exposure actually measured. They are deliberately
#: simple: a defensible published construction beats an unverifiable proprietary
#: one when the alternative is having no model at all.
STYLE_FACTOR_DEFINITIONS: Mapping[str, Mapping[str, int]] = {
    # Fama-French SMB direction: small minus big, so smaller cap = larger exposure.
    "size": {"log_market_cap": -1},
    # HML: book-to-price and earnings-to-price, both larger when cheaper.
    "value": {"book_to_price": 1, "earnings_to_price": 1},
    "growth": {"sales_growth": 1, "earnings_growth": 1},
    # Jegadeesh-Titman: 12-month return skipping the most recent month, because
    # the skipped month carries short-term reversal, not momentum.
    "momentum": {"return_12m_ex_1m": 1},
    "quality": {"return_on_equity": 1, "gross_profitability": 1},
    # Low-volatility anomaly: less volatile = larger exposure.
    "low_volatility": {"realised_volatility": -1},
    "leverage": {"debt_to_equity": 1},
    # Amihud illiquidity inverted, so larger exposure = more liquid.
    "liquidity": {"turnover": 1},
}


@dataclass(frozen=True)
class FactorReturnFit:
    """One date's cross-sectional regression of returns on exposures.

    Attributes:
        date: Label of the return date.
        factor_returns: Estimated return per unit of exposure, indexed by factor
            name. Includes :data:`MARKET_FACTOR` as the intercept.
        t_statistics: Coefficient t-statistics on the same index.
        residuals: Per-asset specific return, indexed by asset.
        r_squared: Fraction of the cross-sectional return variance explained.
        observations: Assets in the regression.
    """

    date: object
    factor_returns: pd.Series
    t_statistics: pd.Series
    residuals: pd.Series
    r_squared: float
    observations: int


@dataclass(frozen=True)
class StyleDrift:
    """How much a portfolio's exposures moved over the observed history.

    Attributes:
        mean_exposure: Average exposure per factor across the history.
        std_exposure: Standard deviation of exposure per factor -- the drift
            measure itself.
        first_exposure: Exposure at the first observed date.
        last_exposure: Exposure at the last observed date.
        total_change: ``last_exposure - first_exposure``.
        max_abs_change: Largest absolute period-on-period move per factor. A
            fund can end where it started having gone somewhere else entirely,
            and this is the column that shows it.
    """

    mean_exposure: pd.Series
    std_exposure: pd.Series
    first_exposure: pd.Series
    last_exposure: pd.Series
    total_change: pd.Series
    max_abs_change: pd.Series


def standardise_exposures(
    values: pd.Series,
    market_caps: pd.Series | None = None,
    winsorise: float = DEFAULT_WINSORISE,
) -> pd.Series:
    """Turn a raw characteristic into a cross-sectional exposure.

    Winsorises both tails, then subtracts a cap-weighted mean and divides by an
    equal-weighted standard deviation. See the module docstring for why those
    two weightings differ.

    Args:
        values: Raw characteristic, indexed by asset. NaN entries survive as NaN
            and are the caller's to fill (:func:`build_style_exposures` fills
            them with zero and counts them).
        market_caps: Market capitalisation on the same index, used for the mean.
            When None, the mean is equal-weighted.
        winsorise: Fraction trimmed from each tail, in ``[0, 0.5)``.

    Returns:
        Standardised exposures on the input index.

    Raises:
        ValueError: If ``winsorise`` is outside ``[0, 0.5)``, if fewer than
            :data:`MIN_CROSS_SECTION` finite values are present, or if
            ``market_caps`` does not cover the same index.
    """
    if not 0.0 <= winsorise < 0.5:
        raise ValueError(f"winsorise must be in [0, 0.5), got {winsorise}")

    series = pd.Series(values, dtype=float)
    finite = series.dropna()
    if finite.size < MIN_CROSS_SECTION:
        raise ValueError(
            f"a cross-section needs at least {MIN_CROSS_SECTION} finite values to "
            f"standardise, got {finite.size}"
        )

    if winsorise > 0:
        lower, upper = finite.quantile(winsorise), finite.quantile(1.0 - winsorise)
        clipped = series.clip(lower=lower, upper=upper)
    else:
        clipped = series

    if market_caps is None:
        centre = float(clipped.dropna().mean())
    else:
        caps = pd.Series(market_caps, dtype=float)
        missing = series.index.difference(caps.index)
        if len(missing):
            raise ValueError(
                f"market_caps is missing {len(missing)} asset(s) present in values"
            )
        aligned_caps = caps.reindex(clipped.index)
        usable = clipped.notna() & aligned_caps.notna() & (aligned_caps > 0)
        if not usable.any():
            raise ValueError("no asset has both a finite value and a positive market cap")
        weights = aligned_caps[usable]
        centre = float((clipped[usable] * weights).sum() / weights.sum())

    spread = float(clipped.dropna().std(ddof=1))
    if not np.isfinite(spread) or spread <= 0.0:
        raise ValueError(
            "the characteristic has no cross-sectional variation, so a z-score "
            "would divide by zero"
        )
    return (clipped - centre) / spread


def build_style_exposures(
    characteristics: pd.DataFrame,
    market_caps: pd.Series | None = None,
    definitions: Mapping[str, Mapping[str, int]] = STYLE_FACTOR_DEFINITIONS,
    winsorise: float = DEFAULT_WINSORISE,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Assemble a style exposure matrix from raw characteristics.

    Args:
        characteristics: Raw values, rows indexed by asset, one column per
            characteristic named in ``definitions``. Columns a definition asks
            for but the frame does not carry cause that factor to be skipped,
            reported through the returned fill counts.
        market_caps: Market capitalisation by asset, for the cap-weighted mean.
        definitions: Factor construction map; defaults to
            :data:`STYLE_FACTOR_DEFINITIONS`.
        winsorise: Fraction trimmed from each tail before standardising.

    Returns:
        Tuple of ``(exposures, filled)``. ``exposures`` has one row per asset
        and one column per constructible factor. ``filled`` maps each factor to
        the number of assets whose exposure was imputed as zero because the
        underlying characteristic was missing -- a factor with most of its cells
        filled is not a measurement and the caller must be able to see that.

    Raises:
        ValueError: If ``characteristics`` is empty, or if no factor at all can
            be built from the columns supplied.
    """
    if characteristics.empty:
        raise ValueError("characteristics frame is empty")

    columns: dict[str, pd.Series] = {}
    filled: dict[str, int] = {}

    for factor, recipe in definitions.items():
        available = {c: s for c, s in recipe.items() if c in characteristics.columns}
        if not available:
            continue

        parts = []
        for characteristic, sign in available.items():
            raw = characteristics[characteristic]
            try:
                standardised = standardise_exposures(
                    raw, market_caps=market_caps, winsorise=winsorise
                )
            except ValueError:
                # A single unusable characteristic must not take the whole factor
                # down when the factor has other inputs.
                continue
            parts.append(standardised * sign)

        if not parts:
            continue

        combined = pd.concat(parts, axis=1).mean(axis=1)
        filled[factor] = int(combined.isna().sum())
        columns[factor] = combined.fillna(0.0)

    if not columns:
        raise ValueError(
            "no factor could be built; characteristics carries none of the "
            f"columns any definition needs: {sorted(characteristics.columns)}"
        )
    return pd.DataFrame(columns), filled


def cross_sectional_factor_returns(
    returns: pd.Series,
    exposures: pd.DataFrame,
    market_caps: pd.Series | None = None,
    date: object = None,
) -> FactorReturnFit:
    """Regress one date's asset returns on their exposures.

    The coefficients are that date's factor returns. Weighting is by square-root
    market cap when caps are supplied, which is the standard choice: it respects
    that small-cap residuals are noisier without letting megacaps set the fit.

    Args:
        returns: Asset returns for the date being explained, indexed by asset.
        exposures: Exposure matrix from the *previous* date, rows indexed by
            asset. Using the same date's exposures would be a look-ahead: the
            characteristic and the return would share information.
        market_caps: Market capitalisation by asset for the regression weights.
            When None the regression is unweighted.
        date: Label recorded on the result. Purely informational.

    Returns:
        A :class:`FactorReturnFit`.

    Raises:
        ValueError: If fewer than :data:`MIN_CROSS_SECTION` assets are common to
            the inputs, if the design matrix has more columns than rows, or if
            the exposures are perfectly collinear.
    """
    common = returns.dropna().index.intersection(exposures.dropna(how="any").index)
    if len(common) < MIN_CROSS_SECTION:
        raise ValueError(
            f"cross-sectional regression needs at least {MIN_CROSS_SECTION} assets "
            f"with both a return and full exposures, got {len(common)}"
        )

    y = returns.loc[common].to_numpy(dtype=float)
    factor_names = list(exposures.columns)
    design = np.column_stack(
        [np.ones(len(common)), exposures.loc[common].to_numpy(dtype=float)]
    )
    names = [MARKET_FACTOR, *factor_names]

    if design.shape[1] > design.shape[0]:
        raise ValueError(
            f"{design.shape[1]} regressors but only {design.shape[0]} assets; "
            "the fit would be exactly determined and meaningless"
        )

    if market_caps is None:
        weights = np.ones(len(common))
    else:
        caps = pd.Series(market_caps, dtype=float).reindex(common)
        if caps.isna().any() or (caps <= 0).any():
            raise ValueError(
                "market_caps must be positive and defined for every asset in the "
                "regression"
            )
        weights = np.sqrt(caps.to_numpy(dtype=float))

    sqrt_w = np.sqrt(weights)
    design_w = design * sqrt_w[:, None]
    y_w = y * sqrt_w

    rank = np.linalg.matrix_rank(design_w)
    if rank < design_w.shape[1]:
        raise ValueError(
            "the exposure matrix is collinear with the market factor or with "
            "itself, so the coefficients are not identified"
        )

    coefficients, *_ = np.linalg.lstsq(design_w, y_w, rcond=None)
    fitted = design @ coefficients
    residuals = y - fitted

    dof = len(common) - design.shape[1]
    weighted_residuals = y_w - design_w @ coefficients
    sigma_squared = float(weighted_residuals @ weighted_residuals / dof) if dof > 0 else np.nan
    try:
        covariance = sigma_squared * np.linalg.inv(design_w.T @ design_w)
        standard_errors = np.sqrt(np.diag(covariance))
    except np.linalg.LinAlgError:  # pragma: no cover - guarded by the rank check
        standard_errors = np.full(design.shape[1], np.nan)

    with np.errstate(divide="ignore", invalid="ignore"):
        t_stats = np.where(standard_errors > 0, coefficients / standard_errors, np.nan)

    total_variance = float(np.sum((y - y.mean()) ** 2))
    r_squared = (
        1.0 - float(residuals @ residuals) / total_variance if total_variance > 0 else np.nan
    )

    return FactorReturnFit(
        date=date,
        factor_returns=pd.Series(coefficients, index=names, name="factor_return"),
        t_statistics=pd.Series(t_stats, index=names, name="t_statistic"),
        residuals=pd.Series(residuals, index=common, name="specific_return"),
        r_squared=r_squared,
        observations=len(common),
    )


def portfolio_style_exposure(
    holdings: pd.Series,
    exposures: pd.DataFrame,
    benchmark: pd.Series | None = None,
) -> pd.Series:
    """Aggregate asset exposures into a portfolio exposure.

    Args:
        holdings: Portfolio weights by asset. Need not sum to 1; the weights are
            used as supplied, so a book that is 60% invested reports a 60%-scaled
            exposure, which is the honest reading.
        exposures: Exposure matrix, rows indexed by asset.
        benchmark: Benchmark weights by asset. When supplied, the result is the
            ACTIVE exposure (portfolio minus benchmark), which is what an
            attribution conversation is about.

    Returns:
        Exposure per factor. Assets held but absent from ``exposures`` are
        reported through the ``unmatched_weight`` entry rather than dropped, so
        a portfolio half of whose weight had no exposure data cannot read as a
        clean measurement.

    Raises:
        ValueError: If ``holdings`` is empty or ``exposures`` has no columns.
    """
    weights = pd.Series(holdings, dtype=float).dropna()
    if weights.empty:
        raise ValueError("holdings is empty")
    if exposures.shape[1] == 0:
        raise ValueError("exposures has no factor columns")

    matched = weights.index.intersection(exposures.index)
    unmatched_weight = float(weights.drop(matched).abs().sum())
    result = exposures.loc[matched].mul(weights.loc[matched], axis=0).sum()

    if benchmark is not None:
        bench = pd.Series(benchmark, dtype=float).dropna()
        bench_matched = bench.index.intersection(exposures.index)
        unmatched_weight += float(bench.drop(bench_matched).abs().sum())
        result = result - exposures.loc[bench_matched].mul(
            bench.loc[bench_matched], axis=0
        ).sum()

    result["unmatched_weight"] = unmatched_weight
    return result


def style_drift(exposure_history: pd.DataFrame) -> StyleDrift:
    """Summarise how a portfolio's exposures moved over time.

    Args:
        exposure_history: Rows indexed by date in chronological order, one
            column per factor, each cell a portfolio-level exposure from
            :func:`portfolio_style_exposure`.

    Returns:
        A :class:`StyleDrift`.

    Raises:
        ValueError: If fewer than two dates are supplied -- drift is a change,
            and one observation cannot express one.
    """
    if exposure_history.shape[0] < 2:
        raise ValueError(
            f"style drift needs at least 2 dates, got {exposure_history.shape[0]}"
        )

    frame = exposure_history.drop(columns=["unmatched_weight"], errors="ignore")
    return StyleDrift(
        mean_exposure=frame.mean(),
        std_exposure=frame.std(ddof=1),
        first_exposure=frame.iloc[0],
        last_exposure=frame.iloc[-1],
        total_change=frame.iloc[-1] - frame.iloc[0],
        max_abs_change=frame.diff().abs().max(),
    )


def factor_return_attribution(
    portfolio_exposures: pd.Series,
    factor_returns: pd.Series,
    portfolio_return: float,
) -> pd.Series:
    """Split a portfolio return into factor contributions plus a specific residual.

    Args:
        portfolio_exposures: Portfolio exposure per factor.
        factor_returns: Factor return per factor over the same period.
        portfolio_return: The realised portfolio return being explained.

    Returns:
        Contribution per factor (exposure times factor return), plus a
        ``specific`` entry holding the unexplained remainder and a ``total``
        entry equal to ``portfolio_return``. The parts sum to the total by
        construction: the residual is defined as what is left, never estimated
        separately, so no reconciliation gap can appear.

    Raises:
        ValueError: If the two inputs share no factor.
    """
    exposures = pd.Series(portfolio_exposures, dtype=float).drop(
        labels=["unmatched_weight"], errors="ignore"
    )
    returns = pd.Series(factor_returns, dtype=float)
    shared = exposures.index.intersection(returns.index)
    if shared.empty:
        raise ValueError(
            "portfolio_exposures and factor_returns share no factor; "
            f"exposures={sorted(exposures.index)} returns={sorted(returns.index)}"
        )

    contributions = exposures.loc[shared] * returns.loc[shared]
    explained = float(contributions.sum())
    contributions["specific"] = portfolio_return - explained
    contributions["total"] = portfolio_return
    return contributions
