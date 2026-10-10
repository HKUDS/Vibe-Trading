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
from scipy.stats import rankdata, skew, kurtosis, t as student_t

__all__ = [
    "DEFAULT_WINSORISE",
    "MARKET_FACTOR",
    "MIN_CROSS_SECTION",
    "STYLE_FACTOR_DEFINITIONS",
    "FactorReturnFit",
    "FactorRiskDecomposition",
    "FactorICResult",
    "StyleDrift",
    "standardise_exposures",
    "build_style_exposures",
    "cross_sectional_factor_returns",
    "portfolio_style_exposure",
    "style_drift",
    "factor_return_attribution",
    "factor_risk_decomposition",
    "factor_ic_analysis",
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
class FactorICResult:
    """Summary of cross-sectional Information Coefficient (IC) time-series dynamics.

    Attributes:
        ic_mean: Mean Information Coefficient across observed cross-sections.
        ic_std: Sample standard deviation (ddof=1) of the IC time series.
        ic_ir: Information Ratio of the factor IC (mean / std).
        ic_t_stat: t-statistic for H0: mean IC == 0.
        ic_p_value: Two-sided p-value of ic_t_stat.
        ic_skewness: Skewness of the daily IC distribution.
        ic_kurtosis: Non-excess kurtosis (3.0 for normal) of the daily IC distribution.
        positive_ic_fraction: Fraction of cross-sections with positive IC.
        n_periods: Number of valid cross-sectional dates evaluated.
        ic_series: Time series of cross-sectional IC values per date.
    """

    ic_mean: float
    ic_std: float
    ic_ir: float
    ic_t_stat: float
    ic_p_value: float
    ic_skewness: float
    ic_kurtosis: float
    positive_ic_fraction: float
    n_periods: int
    ic_series: pd.Series

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



@dataclass(frozen=True)
class FactorRiskDecomposition:
    """Portfolio risk decomposition into factor and asset-specific components.

    Attributes:
        total_variance: Total portfolio variance.
        total_volatility: Total portfolio volatility (standard deviation).
        factor_variance: Portfolio variance explained by common factors.
        factor_volatility: Portfolio volatility from common factors.
        specific_variance: Portfolio variance from asset-specific (idiosyncratic) risk.
        specific_volatility: Portfolio volatility from asset-specific risk.
        factor_variance_fraction: Fraction of total variance explained by factors.
        specific_variance_fraction: Fraction of total variance from idiosyncratic risk.
        portfolio_exposures: Portfolio exposures across factors.
        factor_marginal_contributions: Marginal contribution to risk (MCR) per factor.
        factor_risk_contributions: Absolute risk contribution per factor (sums to factor risk).
        factor_pcr: Percentage contribution to risk (PCR) per factor.
        asset_marginal_contributions: Marginal contribution to risk (MCR) per asset.
        asset_risk_contributions: Absolute risk contribution per asset (sums to total volatility).
        asset_pcr: Percentage contribution to risk (PCR) per asset (sums to 1.0 when total_volatility > 0, otherwise zero).
        specific_risk_contributions: Specific risk contribution per asset.
        specific_pcr: Percentage contribution from specific risk per asset.
        unmatched_weight: Portfolio weight in assets lacking factor exposure data.
    """

    total_variance: float
    total_volatility: float
    factor_variance: float
    factor_volatility: float
    specific_variance: float
    specific_volatility: float
    factor_variance_fraction: float
    specific_variance_fraction: float
    portfolio_exposures: pd.Series
    factor_marginal_contributions: pd.Series
    factor_risk_contributions: pd.Series
    factor_pcr: pd.Series
    asset_marginal_contributions: pd.Series
    asset_risk_contributions: pd.Series
    asset_pcr: pd.Series
    specific_risk_contributions: pd.Series
    specific_pcr: pd.Series
    unmatched_weight: float = 0.0

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

    # A row missing any factor cannot describe this asset's style. Exclude
    # it as a whole and report its absolute weight rather than summing NaNs
    # into an apparently measured zero exposure.
    exposures = exposures.loc[np.isfinite(exposures.to_numpy(dtype=float)).all(axis=1)]
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


def factor_risk_decomposition(
    portfolio_weights: pd.Series | Mapping[str, float],
    exposures: pd.DataFrame,
    factor_cov: pd.DataFrame,
    specific_variances: pd.Series | Mapping[str, float] | None = None,
) -> FactorRiskDecomposition:
    """Decompose portfolio risk into systematic factor and idiosyncratic components.

    Implements the Euler homogeneous risk decomposition for multi-factor models
    (Barra/Axioma standard framework):

        Total Variance = w^T X Sigma_F X^T w + w^T D w

    where:
      * ``w`` is the portfolio weight vector (N x 1)
      * ``X`` is the asset factor exposure matrix (N x K)
      * ``Sigma_F`` is the factor covariance matrix (K x K)
      * ``D`` is the diagonal matrix of specific variances (N x N)

    Args:
        portfolio_weights: Asset weights in the portfolio.
        exposures: Asset factor exposures (rows = assets, columns = factors).
        factor_cov: Covariance matrix of factor returns (K x K).
        specific_variances: Asset-specific (idiosyncratic) return variances.
            Defaults to zero if omitted.

    Returns:
        :class:`FactorRiskDecomposition` containing total/factor/specific
        variances, volatilities, marginal contributions to risk (MCR), and
        percentage contributions to risk (PCR) per factor and per asset.

    Raises:
        ValueError: If weights or matrices are empty, contain non-finite values,
            or share no common assets or factors.
    """
    w_series = pd.Series(portfolio_weights, dtype=float)
    if w_series.empty:
        raise ValueError("portfolio_weights cannot be empty")
    if not np.isfinite(w_series.values).all():
        raise ValueError("portfolio_weights contains non-finite values")

    if not isinstance(exposures, pd.DataFrame) or exposures.empty:
        raise ValueError("exposures must be a non-empty DataFrame")
    if not np.isfinite(exposures.values).all():
        raise ValueError("exposures contains non-finite values")

    if not isinstance(factor_cov, pd.DataFrame) or factor_cov.empty:
        raise ValueError("factor_cov must be a non-empty DataFrame")
    if not np.isfinite(factor_cov.values).all():
        raise ValueError("factor_cov contains non-finite values")

    # Align assets
    assets = w_series.index.intersection(exposures.index)
    if assets.empty:
        raise ValueError(
            f"No matching assets between weights ({sorted(w_series.index)}) and exposures ({sorted(exposures.index)})"
        )

    unmatched_weight = float(w_series.drop(index=assets, errors="ignore").abs().sum())
    w = w_series.loc[assets]
    X = exposures.loc[assets]

    # Align factors
    factors = X.columns.intersection(factor_cov.index).intersection(factor_cov.columns)
    if factors.empty:
        raise ValueError(
            f"No matching factors between exposures ({sorted(X.columns)}) and factor_cov ({sorted(factor_cov.index)})"
        )

    X = X[factors]
    F = factor_cov.loc[factors, factors]
    F_mat = F.to_numpy(dtype=float)
    if not np.allclose(F_mat, F_mat.T, atol=1e-8):
        raise ValueError("factor_cov matrix must be symmetric")
    eigvals = np.linalg.eigvalsh(F_mat)
    if np.min(eigvals) < -1e-8:
        raise ValueError("factor_cov matrix must be positive semi-definite")

    # Align specific variances
    if specific_variances is not None:
        spec_var_s = pd.Series(specific_variances, dtype=float)
        if not np.isfinite(spec_var_s.values).all():
            raise ValueError("specific_variances contains non-finite values")
        d = spec_var_s.reindex(assets, fill_value=0.0).clip(lower=0.0)
    else:
        d = pd.Series(0.0, index=assets, dtype=float)

    # Portfolio factor exposure: x_p = X^T w (K x 1)
    x_p = X.T.dot(w)

    # Factor variance: x_p^T F x_p
    F_x_p = F.dot(x_p)
    factor_var = float(np.maximum(0.0, x_p.dot(F_x_p)))
    factor_vol = float(np.sqrt(factor_var))

    # Specific variance: sum(w_i^2 * d_i)
    spec_var = float(np.maximum(0.0, (w**2 * d).sum()))
    spec_vol = float(np.sqrt(spec_var))

    total_var = float(np.maximum(0.0, factor_var + spec_var))
    total_vol = float(np.sqrt(total_var))

    var_denom = total_var if total_var > 0 else 1.0
    factor_var_frac = factor_var / var_denom if total_var > 0 else 0.0
    spec_var_frac = spec_var / var_denom if total_var > 0 else 0.0

    if total_vol > 0:
        # Factor MCR = (F x_p) / total_vol
        factor_mcr = F_x_p / total_vol
        factor_rc = x_p * factor_mcr
        factor_pcr = factor_rc / total_vol

        # Specific risk contribution per asset = (w_i^2 * d_i) / total_vol
        spec_rc = (w**2 * d) / total_vol
        spec_pcr = spec_rc / total_vol

        # Asset MCR = (X (F x_p) + d * w) / total_vol
        asset_mcr = (X.dot(F_x_p) + d * w) / total_vol
        asset_rc = w * asset_mcr
        asset_pcr = asset_rc / total_vol
    else:
        factor_mcr = pd.Series(0.0, index=factors, dtype=float)
        factor_rc = pd.Series(0.0, index=factors, dtype=float)
        factor_pcr = pd.Series(0.0, index=factors, dtype=float)
        spec_rc = pd.Series(0.0, index=assets, dtype=float)
        spec_pcr = pd.Series(0.0, index=assets, dtype=float)
        asset_mcr = pd.Series(0.0, index=assets, dtype=float)
        asset_rc = pd.Series(0.0, index=assets, dtype=float)
        asset_pcr = pd.Series(0.0, index=assets, dtype=float)

    return FactorRiskDecomposition(
        total_variance=total_var,
        total_volatility=total_vol,
        factor_variance=factor_var,
        factor_volatility=factor_vol,
        specific_variance=spec_var,
        specific_volatility=spec_vol,
        factor_variance_fraction=factor_var_frac,
        specific_variance_fraction=spec_var_frac,
        portfolio_exposures=x_p,
        factor_marginal_contributions=factor_mcr,
        factor_risk_contributions=factor_rc,
        factor_pcr=factor_pcr,
        asset_marginal_contributions=asset_mcr,
        asset_risk_contributions=asset_rc,
        asset_pcr=asset_pcr,
        specific_risk_contributions=spec_rc,
        specific_pcr=spec_pcr,
        unmatched_weight=unmatched_weight,
    )


def factor_ic_analysis(
    factor_panel: pd.DataFrame,
    forward_returns: pd.DataFrame,
    method: str = "spearman",
    min_cross_section: int = MIN_CROSS_SECTION,
) -> FactorICResult:
    """Evaluate cross-sectional Information Coefficient (IC) time-series dynamics.

    Measures the predictive power and persistence of a factor by calculating
    daily/periodic cross-sectional correlations between factor scores and subsequent
    forward returns (Grinold-Kahn fundamental law framework).

    Args:
        factor_panel: DataFrame of factor scores (index = dates, columns = assets).
        forward_returns: DataFrame of forward returns (same shape and alignment; should be pre-shifted by caller).
        method: Correlation method, ``'spearman'`` (Rank IC) or ``'pearson'`` (Linear IC).
        min_cross_section: Minimum number of valid assets on a date to compute IC.

    Returns:
        :class:`FactorICResult` containing mean IC, IC IR, t-statistic, p-value,
        higher moments, and full IC time series.

    Raises:
        ValueError: If inputs are empty, share no common dates or assets, or method is unknown.
    """
    if method not in ("spearman", "pearson"):
        raise ValueError(f"method must be 'spearman' or 'pearson', got {method!r}")

    if factor_panel.empty or forward_returns.empty:
        raise ValueError("factor_panel and forward_returns must be non-empty")

    # Align dates and assets
    common_dates = factor_panel.index.intersection(forward_returns.index)
    common_assets = factor_panel.columns.intersection(forward_returns.columns)

    if common_dates.empty or common_assets.empty:
        raise ValueError("No common dates and assets between factor_panel and forward_returns")

    f_sub = factor_panel.loc[common_dates, common_assets]
    r_sub = forward_returns.loc[common_dates, common_assets]

    ic_records: dict[object, float] = {}

    for date in common_dates:
        f_row = f_sub.loc[date].dropna()
        r_row = r_sub.loc[date].dropna()
        shared = f_row.index.intersection(r_row.index)
        if len(shared) < min_cross_section:
            continue

        f_vals = f_row.loc[shared].to_numpy(dtype=float)
        r_vals = r_row.loc[shared].to_numpy(dtype=float)

        if method == "spearman":
            f_vals = rankdata(f_vals)
            r_vals = rankdata(r_vals)

        f_std = np.std(f_vals, ddof=1)
        r_std = np.std(r_vals, ddof=1)

        if f_std > 0 and r_std > 0:
            corr = float(np.corrcoef(f_vals, r_vals)[0, 1])
            if np.isfinite(corr):
                ic_records[date] = corr

    if not ic_records:
        raise ValueError(
            f"No cross-section had at least {min_cross_section} valid asset pairs to compute IC"
        )

    ic_series = pd.Series(ic_records, dtype=float, name="ic").sort_index()
    n = len(ic_series)
    mean_ic = float(ic_series.mean())

    if n > 1:
        std_ic = float(ic_series.std(ddof=1))
        ic_ir = mean_ic / std_ic if std_ic > 0 else float("nan")
        t_stat = ic_ir * np.sqrt(n) if std_ic > 0 else float("nan")
        p_val = float(2 * student_t.sf(abs(t_stat), df=n - 1)) if np.isfinite(t_stat) else float("nan")
        sk = float(skew(ic_series.to_numpy(), bias=False)) if n > 2 else 0.0
        # Non-excess kurtosis (normal == 3.0)
        kurt = float(kurtosis(ic_series.to_numpy(), fisher=False, bias=False)) if n > 3 else 3.0
    else:
        std_ic = float("nan")
        ic_ir = float("nan")
        t_stat = float("nan")
        p_val = float("nan")
        sk = 0.0
        kurt = 3.0

    pos_frac = float((ic_series > 0).mean()) if n > 0 else 0.0

    return FactorICResult(
        ic_mean=mean_ic,
        ic_std=std_ic,
        ic_ir=ic_ir,
        ic_t_stat=t_stat,
        ic_p_value=p_val,
        ic_skewness=sk,
        ic_kurtosis=kurt,
        positive_ic_fraction=pos_frac,
        n_periods=n,
        ic_series=ic_series,
    )
