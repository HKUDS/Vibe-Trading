"""Credit-risk primitives: Altman Z-Score, Merton/KMV, and spread analytics.

Executable form of the credit models that used to live as markdown code blocks
in ``src/skills/credit-analysis/SKILL.md``. Differences from those originals are
deliberate and each is called out in the relevant docstring; the two that bite
hardest are:

* **Spread input units are explicit.** The markdown's two spread helpers
  disagreed with each other -- :func:`credit_spread_analysis` multiplied by 100
  (yields in percent) while :func:`spread_term_structure` multiplied by 10000
  (yields in decimals). Both now take ``input_unit``, defaulting to whatever the
  markdown silently assumed, so neither changes behaviour but neither can be
  misread.
* **Altman's X4 denominator is total liabilities**, not "total debt". The skill's
  own variable table says 总负债账面值; the markdown's parameter name said
  ``total_debt``. The name here follows the model.

All rates and ratios are decimals unless a name ends in ``_bp``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import fsolve
from scipy.stats import norm

__all__ = [
    "ALTMAN_MODELS",
    "AltmanModelSpec",
    "AltmanZScore",
    "MertonResult",
    "SPREAD_INPUT_UNITS",
    "EDF_REFERENCE_BANDS",
    "MERTON_SOLVER_RESTARTS",
    "MERTON_SOLVER_STEP_TOL",
    "ZONE_LABELS_ZH",
    "altman_z_score",
    "merton_asset_solve",
    "merton_model",
    "distance_to_default",
    "kmv_default_point",
    "kmv_distance_to_default",
    "edf_reference_band",
    "credit_spread_analysis",
    "spread_term_structure",
]


@dataclass(frozen=True)
class AltmanModelSpec:
    """Coefficients and cut-offs of one Altman Z-Score variant.

    Attributes:
        coefficients: Weights on ``(X1, X2, X3, X4, X5)``. ``X5`` carries a
            weight of 0.0 in variants that drop the asset-turnover term.
        safe_threshold: Scores strictly above this sit in the safe zone.
        distress_threshold: Scores strictly below this sit in the distress zone.
        uses_x5: Whether the variant needs a revenue figure at all.
        equity_basis: What ``equity_value`` must be for this variant --
            ``"market"`` for the market capitalisation, ``"book"`` for the book
            value of equity.
    """

    coefficients: tuple[float, float, float, float, float]
    safe_threshold: float
    distress_threshold: float
    uses_x5: bool
    equity_basis: str


#: The three published Altman variants carried by the credit-analysis skill.
ALTMAN_MODELS: Mapping[str, AltmanModelSpec] = {
    # Altman (1968), listed manufacturers.
    "original": AltmanModelSpec((1.2, 1.4, 3.3, 0.6, 1.0), 2.99, 1.81, True, "market"),
    # Z' -- privately held firms; X4 switches to book equity.
    "prime": AltmanModelSpec(
        (0.717, 0.847, 3.107, 0.420, 0.998), 2.90, 1.23, True, "book"
    ),
    # Z'' -- non-manufacturers / emerging markets; X5 dropped entirely.
    "double_prime": AltmanModelSpec((6.56, 3.26, 6.72, 1.05, 0.0), 2.60, 1.10, False, "book"),
}

#: Chinese labels for the three Z-Score zones, as printed in the skill.
ZONE_LABELS_ZH: Mapping[str, str] = {
    "safe": "安全区（低违约风险）",
    "grey": "灰色区（需深入分析）",
    "distress": "危险区（高违约风险）",
}


@dataclass(frozen=True)
class AltmanZScore:
    """Outcome of an Altman Z-Score evaluation.

    Attributes:
        z_score: The composite score.
        model: Which variant produced it; a key of :data:`ALTMAN_MODELS`.
        zone: ``"safe"``, ``"grey"`` or ``"distress"``.
        label_zh: The Chinese zone label from :data:`ZONE_LABELS_ZH`.
        components: The ``X1``..``X5`` ratios. ``x5`` is ``None`` for variants
            that do not use it.
        safe_threshold: Cut-off above which the zone is ``"safe"``.
        distress_threshold: Cut-off below which the zone is ``"distress"``.
    """

    z_score: float
    model: str
    zone: str
    label_zh: str
    components: Mapping[str, float | None]
    safe_threshold: float
    distress_threshold: float


def altman_z_score(
    *,
    working_capital: float,
    retained_earnings: float,
    ebit: float,
    equity_value: float,
    total_liabilities: float,
    total_assets: float,
    revenue: float | None = None,
    model: str = "original",
) -> AltmanZScore:
    """Score a firm's distress risk with one of the three Altman variants.

    Every argument is keyword-only, deliberately. Six interchangeable float
    parameters is exactly the shape where a positional call silently computes
    the wrong answer, and this signature does not match the argument order of
    the markdown block it replaced -- ``revenue`` and ``total_assets`` are
    swapped relative to it. A positional call written from memory of the old
    block would divide by revenue and return a confident, wrong Z with no
    error. Keyword-only makes that a ``TypeError`` instead.

    Args:
        working_capital: Current assets less current liabilities.
        retained_earnings: Cumulative retained earnings.
        ebit: Earnings before interest and tax.
        equity_value: Market capitalisation for ``"original"``; book value of
            equity for ``"prime"`` and ``"double_prime"``. The required basis is
            recorded on each :class:`AltmanModelSpec`.
        total_liabilities: Book value of *all* liabilities, not just interest
            bearing debt. This is the X4 denominator in Altman's definition.
        total_assets: Total assets; the denominator of X1, X2, X3 and X5.
        revenue: Sales for the period. Required unless the variant drops X5.
        model: A key of :data:`ALTMAN_MODELS`.

    Returns:
        An :class:`AltmanZScore` with the score, the zone and every input ratio.

    Raises:
        ValueError: If ``model`` is unknown, a denominator is zero, or the
            variant needs ``revenue`` and it was not supplied.
    """
    spec = ALTMAN_MODELS.get(model)
    if spec is None:
        raise ValueError(
            f"unknown model {model!r}; expected one of {tuple(ALTMAN_MODELS)}"
        )
    if total_assets == 0:
        raise ValueError("total_assets must be non-zero")
    if total_liabilities == 0:
        raise ValueError("total_liabilities must be non-zero")
    if spec.uses_x5 and revenue is None:
        raise ValueError(f"model {model!r} needs revenue for the X5 term")

    x1 = working_capital / total_assets
    x2 = retained_earnings / total_assets
    x3 = ebit / total_assets
    x4 = equity_value / total_liabilities
    x5 = revenue / total_assets if spec.uses_x5 else None

    weights = spec.coefficients
    z = weights[0] * x1 + weights[1] * x2 + weights[2] * x3 + weights[3] * x4
    if x5 is not None:
        z += weights[4] * x5

    if z > spec.safe_threshold:
        zone = "safe"
    elif z < spec.distress_threshold:
        zone = "distress"
    else:
        zone = "grey"

    return AltmanZScore(
        z_score=float(z),
        model=model,
        zone=zone,
        label_zh=ZONE_LABELS_ZH[zone],
        components={"x1": x1, "x2": x2, "x3": x3, "x4": x4, "x5": x5},
        safe_threshold=spec.safe_threshold,
        distress_threshold=spec.distress_threshold,
    )


@dataclass(frozen=True)
class MertonResult:
    """Solved Merton structural model for one issuer.

    Attributes:
        asset_value: Implied market value of assets, in the units of the inputs.
        asset_vol: Implied annualised asset volatility as a decimal.
        d1: Black-Scholes ``d1`` on the asset value.
        d2: Black-Scholes ``d2``; equals the risk-neutral distance to default.
        distance_to_default: Distance to default at ``asset_drift``. When the
            drift is the risk-free rate this is exactly ``d2``.
        default_probability: Risk-neutral default probability ``N(-d2)``.
        debt_value: Present value of the risky zero-coupon debt.
        credit_spread: Continuously compounded spread over the risk-free rate,
            as a decimal.
    """

    asset_value: float
    asset_vol: float
    d1: float
    d2: float
    distance_to_default: float
    default_probability: float
    debt_value: float
    credit_spread: float

    @property
    def credit_spread_bp(self) -> float:
        """Credit spread expressed in basis points.

        Returns:
            ``credit_spread`` multiplied by 10000.
        """
        return self.credit_spread * 1e4


def _merton_d1_d2(
    asset_value: float,
    asset_vol: float,
    debt_face: float,
    risk_free: float,
    horizon: float,
) -> tuple[float, float]:
    """Black-Scholes ``d1``/``d2`` for equity written on the firm's assets.

    Args:
        asset_value: Market value of assets.
        asset_vol: Annualised asset volatility as a decimal.
        debt_face: Face value of the zero-coupon debt.
        risk_free: Continuously compounded risk-free rate as a decimal.
        horizon: Years to the debt's maturity.

    Returns:
        Tuple ``(d1, d2)``.
    """
    vol_t = asset_vol * math.sqrt(horizon)
    d1 = (
        math.log(asset_value / debt_face) + (risk_free + 0.5 * asset_vol**2) * horizon
    ) / vol_t
    return d1, d1 - vol_t


#: Step tolerance handed to the Merton root finder. ``fsolve``'s ``xtol`` bounds
#: the *step*, and because the unknowns are solved in log space that step is a
#: relative move in ``sigma_V``. At the SciPy default (~1.5e-8) a low-volatility,
#: high-leverage issuer -- exactly the case Merton is used for -- halts while the
#: scaled residual is still ~1e-7, so convergence is judged on the residual below
#: and the step tolerance is pinned near machine precision instead.
MERTON_SOLVER_STEP_TOL: float = 1e-13

#: Extra solves started from the previous answer when the residual still misses.
MERTON_SOLVER_RESTARTS: int = 2


def merton_asset_solve(
    equity_value: float,
    equity_vol: float,
    debt_face: float,
    risk_free: float,
    horizon: float,
    tolerance: float = 1e-8,
) -> tuple[float, float]:
    """Back out asset value and asset volatility from observable equity.

    Solves the standard pair of equations simultaneously::

        E       = V*N(d1) - D*exp(-r*T)*N(d2)
        sigma_E = N(d1) * sigma_V * V / E

    The unknowns are solved in log space so the root finder cannot wander into a
    negative asset value or a negative volatility, which the markdown version
    could.

    Args:
        equity_value: Market capitalisation.
        equity_vol: Annualised equity volatility as a decimal.
        debt_face: Face value of debt, treated as a single zero-coupon claim.
        risk_free: Continuously compounded risk-free rate as a decimal.
        horizon: Years to the debt's maturity.
        tolerance: Largest residual, relative to ``equity_value``, accepted as a
            solution.

    Returns:
        Tuple ``(asset_value, asset_vol)``.

    Raises:
        ValueError: If any input is non-positive, or the system does not
            converge to within ``tolerance``.
    """
    if min(equity_value, equity_vol, debt_face, horizon) <= 0:
        raise ValueError(
            "equity_value, equity_vol, debt_face and horizon must all be positive"
        )

    def residuals(log_params: np.ndarray) -> list[float]:
        asset_value, asset_vol = np.exp(log_params)
        d1, d2 = _merton_d1_d2(asset_value, asset_vol, debt_face, risk_free, horizon)
        equity_eq = (
            asset_value * norm.cdf(d1)
            - debt_face * math.exp(-risk_free * horizon) * norm.cdf(d2)
            - equity_value
        )
        vol_eq = norm.cdf(d1) * asset_vol * asset_value - equity_vol * equity_value
        return [equity_eq / equity_value, vol_eq / equity_value]

    start_value = equity_value + debt_face * math.exp(-risk_free * horizon)
    point = np.log([start_value, equity_vol * equity_value / start_value])
    for _ in range(MERTON_SOLVER_RESTARTS + 1):
        point = fsolve(
            residuals, point, full_output=True, xtol=MERTON_SOLVER_STEP_TOL
        )[0]
        worst = max(abs(r) for r in residuals(point))
        if math.isfinite(worst) and worst <= tolerance:
            break
    else:
        raise ValueError(
            "Merton system did not converge: worst scaled residual "
            f"{worst:.3g} exceeds tolerance {tolerance:g}"
        )

    asset_value, asset_vol = (float(v) for v in np.exp(point))
    return asset_value, asset_vol


def merton_model(
    equity_value: float,
    equity_vol: float,
    debt_face: float,
    risk_free: float,
    horizon: float,
    asset_drift: float | None = None,
) -> MertonResult:
    """Estimate default probability and credit spread from equity market data.

    Args:
        equity_value: Market capitalisation.
        equity_vol: Annualised equity volatility as a decimal.
        debt_face: Face value of debt, treated as a single zero-coupon claim.
        risk_free: Continuously compounded risk-free rate as a decimal.
        horizon: Years to the debt's maturity.
        asset_drift: Expected asset return used for the real-world distance to
            default. Defaults to ``risk_free``, which is what the markdown did;
            supplying an equity-style drift instead gives the KMV reading.

    Returns:
        A :class:`MertonResult`.

    Raises:
        ValueError: If an input is non-positive or the asset system does not
            converge.
    """
    asset_value, asset_vol = merton_asset_solve(
        equity_value, equity_vol, debt_face, risk_free, horizon
    )
    d1, d2 = _merton_d1_d2(asset_value, asset_vol, debt_face, risk_free, horizon)
    drift = risk_free if asset_drift is None else asset_drift

    discounted_face = debt_face * math.exp(-risk_free * horizon)
    debt_value = float(
        discounted_face * norm.cdf(d2) + asset_value * norm.cdf(-d1)
    )
    spread = -math.log(debt_value / discounted_face) / horizon

    return MertonResult(
        asset_value=asset_value,
        asset_vol=asset_vol,
        d1=d1,
        d2=d2,
        distance_to_default=distance_to_default(
            asset_value, asset_vol, debt_face, horizon, drift
        ),
        default_probability=float(norm.cdf(-d2)),
        debt_value=debt_value,
        credit_spread=spread,
    )


def distance_to_default(
    asset_value: float,
    asset_vol: float,
    default_point: float,
    horizon: float,
    drift: float = 0.0,
) -> float:
    """Merton distance to default, in standard deviations of log asset value.

    Args:
        asset_value: Market value of assets.
        asset_vol: Annualised asset volatility as a decimal.
        default_point: Asset level at which default is triggered. Merton uses
            the full face value of debt; KMV uses :func:`kmv_default_point`.
        horizon: Years to the measurement date.
        drift: Expected asset return. Pass the risk-free rate for the
            risk-neutral reading, an expected return for the real-world one.

    Returns:
        Distance to default. Larger is safer; under a lognormal assumption the
        matching default probability is ``N(-dd)``.

    Raises:
        ValueError: If any of the value, volatility, default point or horizon is
            non-positive.
    """
    if min(asset_value, asset_vol, default_point, horizon) <= 0:
        raise ValueError(
            "asset_value, asset_vol, default_point and horizon must all be positive"
        )
    numerator = math.log(asset_value / default_point) + (
        drift - 0.5 * asset_vol**2
    ) * horizon
    return numerator / (asset_vol * math.sqrt(horizon))


def kmv_default_point(
    short_term_debt: float,
    long_term_debt: float,
    long_term_weight: float = 0.5,
) -> float:
    """KMV default point: all short-term debt plus part of the long-term book.

    Args:
        short_term_debt: Debt maturing inside one year.
        long_term_debt: Debt maturing beyond one year.
        long_term_weight: Fraction of long-term debt included. Moody's KMV uses
            0.5; it is an argument because the calibration is a convention, not
            a result.

    Returns:
        The default point in the units of the inputs.

    Raises:
        ValueError: If either debt figure is negative, or the weight is outside
            ``[0, 1]``.
    """
    if short_term_debt < 0 or long_term_debt < 0:
        raise ValueError("debt figures must be non-negative")
    if not 0.0 <= long_term_weight <= 1.0:
        raise ValueError(f"long_term_weight must lie in [0, 1], got {long_term_weight}")
    return short_term_debt + long_term_weight * long_term_debt


def kmv_distance_to_default(
    asset_value: float,
    asset_vol: float,
    default_point: float,
) -> float:
    """KMV's linear distance to default, ``(V - DP) / (V * sigma_V)``.

    This is the form the skill documents for KMV and is *not* the same quantity
    as :func:`distance_to_default`: it measures the gap in units of the asset
    value's own standard deviation rather than in log space, and it carries no
    horizon or drift. Keep the two apart -- KMV then maps this number to an
    empirical EDF rather than through the normal CDF.

    Args:
        asset_value: Market value of assets.
        asset_vol: Annualised asset volatility as a decimal.
        default_point: Output of :func:`kmv_default_point`.

    Returns:
        Distance to default in standard deviations. Larger is safer; negative
        means assets already sit below the default point.

    Raises:
        ValueError: If ``asset_value`` or ``asset_vol`` is non-positive.
    """
    if asset_value <= 0 or asset_vol <= 0:
        raise ValueError("asset_value and asset_vol must be positive")
    return (asset_value - default_point) / (asset_value * asset_vol)


#: Reference DD-to-EDF bands from the skill, as ``(dd_floor, edf_low, edf_high)``
#: with EDF as decimals. ``math.inf`` marks an open end.
EDF_REFERENCE_BANDS: tuple[tuple[float, float, float], ...] = (
    (4.0, 0.0, 0.001),
    (2.0, 0.001, 0.01),
    (1.0, 0.01, 0.05),
    (-math.inf, 0.05, math.inf),
)


def edf_reference_band(dd: float) -> tuple[float, float]:
    """Look up the indicative EDF range for a distance to default.

    This is the skill's published rule of thumb, not a fitted mapping. A real
    KMV EDF comes from a proprietary default database; treat the output as a
    sanity band and never as a calibrated probability.

    Args:
        dd: Distance to default.

    Returns:
        Tuple ``(edf_low, edf_high)`` as decimals; the upper end is
        ``math.inf`` for the worst band.

    Raises:
        ValueError: If ``dd`` is not a finite number.
    """
    if not math.isfinite(dd):
        raise ValueError(f"dd must be finite, got {dd}")
    for floor, low, high in EDF_REFERENCE_BANDS:
        if dd > floor:
            return low, high
    return EDF_REFERENCE_BANDS[-1][1], EDF_REFERENCE_BANDS[-1][2]


#: Multipliers turning a yield difference into basis points, by input unit.
SPREAD_INPUT_UNITS: Mapping[str, float] = {
    "decimal": 10_000.0,
    "percent": 100.0,
    "bp": 1.0,
}


def _bp_multiplier(input_unit: str) -> float:
    """Resolve a yield input unit to its basis-point multiplier.

    Args:
        input_unit: A key of :data:`SPREAD_INPUT_UNITS`.

    Returns:
        The multiplier that converts the input unit to basis points.

    Raises:
        ValueError: If the unit is not recognised.
    """
    try:
        return SPREAD_INPUT_UNITS[input_unit]
    except KeyError:
        raise ValueError(
            f"unknown input_unit {input_unit!r}; expected one of "
            f"{tuple(SPREAD_INPUT_UNITS)}"
        ) from None


def credit_spread_analysis(
    bond_yields: pd.Series,
    risk_free_yields: pd.Series,
    window: int = 252,
    lookback_periods: int = 21,
    signal_z: float = 1.5,
    input_unit: str = "percent",
) -> pd.DataFrame:
    """Time-series view of an issuer's spread: level, z-score and percentile.

    .. warning::
        ``historical_percentile`` is a **whole-sample** rank, carried over from
        the markdown template this replaced. Every row is ranked against the
        rows that come *after* it as well, so the column is look-ahead biased
        and must never be fed to a backtest as a signal -- the same date will
        report a different percentile once more data arrives. It is a
        descriptive summary of the sample you are holding. ``z_score`` and
        ``signal`` are rolling and therefore causal; use those instead.

    Args:
        bond_yields: Credit yields indexed by date.
        risk_free_yields: Matching risk-free yields on the *same* index. An
            index mismatch raises rather than silently producing NaN, which is
            what plain pandas subtraction would have done.
        window: Rolling window, in observations, for the mean and standard
            deviation. 252 is one trading year.
        lookback_periods: Horizon for the slower change column; 21 is one
            trading month.
        signal_z: Absolute z-score at which the row is flagged rich or cheap.
        input_unit: Unit of the two yield series -- a key of
            :data:`SPREAD_INPUT_UNITS`. Defaults to ``"percent"``, matching the
            markdown template's implicit assumption.

    Returns:
        A DataFrame on the input index with columns ``spread_bp``,
        ``rolling_mean_bp``, ``rolling_std_bp``, ``z_score``,
        ``historical_percentile``, ``change_1p_bp``, ``change_lookback_bp`` and
        ``signal``. ``signal`` is one of ``"rich"``, ``"neutral"``, ``"cheap"``.
        Every column except ``historical_percentile`` is causal; see the warning
        above.

    Raises:
        ValueError: If the two series do not share an index, if ``window`` or
            ``lookback_periods`` is not positive, or if ``input_unit`` is
            unknown.
    """
    if window <= 0 or lookback_periods <= 0:
        raise ValueError("window and lookback_periods must be positive")
    if len(bond_yields) != len(risk_free_yields) or not bond_yields.index.equals(
        risk_free_yields.index
    ):
        raise ValueError("bond_yields and risk_free_yields must share one index")

    spread_bp = (bond_yields - risk_free_yields) * _bp_multiplier(input_unit)

    rolling_mean = spread_bp.rolling(window).mean()
    rolling_std = spread_bp.rolling(window).std()
    z_score = (spread_bp - rolling_mean) / rolling_std

    result = pd.DataFrame(
        {
            "spread_bp": spread_bp,
            "rolling_mean_bp": rolling_mean,
            "rolling_std_bp": rolling_std,
            "z_score": z_score,
            "historical_percentile": spread_bp.rank(pct=True),
            "change_1p_bp": spread_bp.diff(),
            "change_lookback_bp": spread_bp.diff(lookback_periods),
        }
    )
    result["signal"] = "neutral"
    result.loc[z_score < -signal_z, "signal"] = "rich"
    result.loc[z_score > signal_z, "signal"] = "cheap"
    return result


def spread_term_structure(
    issuers: Mapping[str, Mapping[float, float]],
    risk_free_curve: Mapping[float, float] | pd.Series,
    input_unit: str = "decimal",
    decimals: int | None = 1,
) -> pd.DataFrame:
    """Cross-sectional spread grid: one row per issuer, one column per tenor.

    Args:
        issuers: ``{issuer: {tenor_years: yield}}``.
        risk_free_curve: ``{tenor_years: yield}`` on the same unit basis. Tenors
            missing from the curve produce NaN rather than an error, so a
            partially quoted issuer still yields a row.
        input_unit: Unit of every yield passed in -- a key of
            :data:`SPREAD_INPUT_UNITS`. Defaults to ``"decimal"``, matching the
            markdown template's implicit assumption. Note this differs from
            :func:`credit_spread_analysis`, whose template assumed percent.
        decimals: Rounding applied to the basis-point output; ``None`` keeps
            full precision.

    Returns:
        A DataFrame indexed by issuer with one ``"{tenor}Y_spread_bp"`` column
        per tenor seen.

    Raises:
        ValueError: If ``issuers`` is empty or ``input_unit`` is unknown.
    """
    if not issuers:
        raise ValueError("issuers must contain at least one entry")
    multiplier = _bp_multiplier(input_unit)
    curve = dict(risk_free_curve)

    records = []
    for issuer, tenor_curve in issuers.items():
        row: dict[str, float] = {}
        for tenor, yld in tenor_curve.items():
            reference = curve.get(tenor, np.nan)
            spread = (yld - reference) * multiplier
            row[f"{tenor}Y_spread_bp"] = (
                spread if decimals is None else round(spread, decimals)
            )
        records.append(pd.Series(row, name=issuer))
    return pd.DataFrame(records)
