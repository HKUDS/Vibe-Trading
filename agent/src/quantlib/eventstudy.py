"""Event study: abnormal returns around a dated corporate or macro event.

The question this answers is "did the market react to the event, beyond what it
would have done anyway", and the whole method is the *beyond* clause. A raw
return around an earnings date is not evidence of anything: the index moved too.
So a normal-return model is fitted on a window that ends before the event, and
what the model fails to explain during the event window is the abnormal return.

    AR_{i,t}  = R_{i,t} - E[R_{i,t}]          (abnormal return, one day)
    CAR_i     = sum over the event window      (one event's cumulative reaction)
    CAAR      = mean CAR across events         (the sample's average reaction)

THE ESTIMATION WINDOW MUST NOT TOUCH THE EVENT WINDOW
-----------------------------------------------------
If the event's own returns are inside the sample the model was fitted on, the
model has partly learned the event, the residual shrinks toward zero, and the
study under-reports its own finding. :data:`DEFAULT_ESTIMATION_GAP` puts rows
between the two windows, and an overlap is an error rather than a warning.

DAYS ARE ROWS, NOT CALENDAR DAYS
--------------------------------
Relative day ``-1`` means "the row before the event row" in the supplied return
frame. With daily bars that is the previous trading day, which is what event
studies mean by ``t-1``. A frame with gaps, or with a different bar size, shifts
that meaning; the caller owns the frame's spacing.

WHY THREE TEST STATISTICS
-------------------------
``t_statistic``
    Plain cross-sectional t-test on the CARs. Assumes the events are independent
    and equally variable. Fine for a quick read, wrong when a few volatile names
    dominate the sample.

``patell_z``
    Standardises each daily abnormal return by the standard error the estimation
    window implies for it, including the prediction-error term that accounts for
    the market return on that day sitting far from its estimation-window mean.
    Corrects for cross-sectional differences in volatility, but still assumes
    event-window variance equals estimation-window variance.

``bmp_z``
    Boehmer-Musumeci-Poulsen. Standardises like Patell, then takes the
    cross-sectional variance *of the standardised values*. This is the one that
    survives event-induced variance -- events routinely raise volatility, which
    inflates Patell's rejection rate. When the three disagree, BMP is the one to
    report.

None of the three fixes cross-sectional correlation from events that share a
date; clustered event dates need a calendar-time portfolio instead, and this
module says so via :attr:`EventStudyResult.shared_event_dates` rather than
silently reporting an over-confident z.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm, t as student_t

__all__ = [
    "DEFAULT_ESTIMATION_GAP",
    "DEFAULT_ESTIMATION_WINDOW",
    "DEFAULT_EVENT_WINDOW",
    "MIN_ESTIMATION_OBSERVATIONS",
    "NORMAL_RETURN_MODELS",
    "EventOutcome",
    "EventStudyResult",
    "MarketModelFit",
    "estimate_market_model",
    "event_study",
]

#: Rows placed between the end of the estimation window and the start of the
#: event window, so no event-window return can inform the model fitted on it.
DEFAULT_ESTIMATION_GAP: int = 10

#: Rows used to fit the normal-return model.
DEFAULT_ESTIMATION_WINDOW: int = 120

#: Event window in relative rows, inclusive on both ends.
DEFAULT_EVENT_WINDOW: tuple[int, int] = (-5, 5)

#: Fewest estimation observations that still leave the residual variance and the
#: Patell correction meaningful. Below this an event is dropped, not fitted.
MIN_ESTIMATION_OBSERVATIONS: int = 30

#: Normal-return models understood by :func:`event_study`.
#:
#: ``market``          OLS of asset on market: E[R] = alpha + beta * R_m.
#: ``market_adjusted`` beta fixed at 1, alpha at 0: E[R] = R_m. No estimation
#:                     window is needed for the mean, but one is still required
#:                     for the residual variance the tests are scaled by.
#: ``mean_adjusted``   E[R] = mean of the estimation window. Ignores the market.
NORMAL_RETURN_MODELS: tuple[str, ...] = ("market", "market_adjusted", "mean_adjusted")


@dataclass(frozen=True)
class MarketModelFit:
    """Normal-return model fitted on one asset's estimation window.

    Attributes:
        alpha: Intercept. Zero by construction for the non-OLS models.
        beta: Market sensitivity. One for ``market_adjusted``, zero for
            ``mean_adjusted``.
        residual_std: Standard deviation of the estimation-window residuals,
            with the model's degrees of freedom removed.
        observations: Estimation-window rows actually used.
        market_mean: Mean market return over the estimation window, needed by
            the Patell prediction-error correction.
        market_sum_squares: Sum of squared market deviations over the estimation
            window, likewise.
        model: Which entry of :data:`NORMAL_RETURN_MODELS` was fitted.
    """

    alpha: float
    beta: float
    residual_std: float
    observations: int
    market_mean: float
    market_sum_squares: float
    model: str


@dataclass(frozen=True)
class EventOutcome:
    """One event's abnormal returns and cumulative reaction.

    Attributes:
        symbol: Asset the event belongs to.
        event_date: Index label the event was anchored on.
        abnormal_returns: Abnormal return per relative day, indexed by relative
            day, ordered from the window's first day to its last.
        car: Cumulative abnormal return over the whole event window.
        car_std_error: Standard error of ``car`` implied by the estimation
            window, including the Patell prediction-error term.
        standardised_car: ``car / car_std_error``. This is the quantity BMP
            takes a cross-sectional variance of.
        fit: The normal-return model behind these numbers.
    """

    symbol: str
    event_date: object
    abnormal_returns: pd.Series
    car: float
    car_std_error: float
    standardised_car: float
    fit: MarketModelFit


@dataclass(frozen=True)
class EventStudyResult:
    """Aggregate reaction across every event that could be measured.

    Attributes:
        event_window: The ``(start, end)`` relative-row window, inclusive.
        events: Per-event outcomes, in input order, for events that survived.
        dropped: ``(symbol, event_date, reason)`` for each event that could not
            be measured. Never silently omitted -- a study over 40 events of
            which 18 were dropped is a different study.
        aar: Average abnormal return per relative day.
        caar: Cumulative average abnormal return per relative day, the running
            sum of ``aar`` across the window.
        caar_total: ``caar`` at the window's last day, the headline number.
        t_statistic: Cross-sectional t-test on the CARs.
        t_p_value: Two-sided p-value of ``t_statistic``.
        patell_z: Patell standardised-residual z.
        patell_p_value: Two-sided p-value of ``patell_z``.
        bmp_z: Boehmer-Musumeci-Poulsen standardised cross-sectional z.
        bmp_p_value: Two-sided p-value of ``bmp_z``.
        shared_event_dates: Event dates carried by more than one event. Non-empty
            means the events overlap in calendar time, the independence every
            statistic here assumes is violated, and the p-values are optimistic.
    """

    event_window: tuple[int, int]
    events: tuple[EventOutcome, ...]
    dropped: tuple[tuple[str, object, str], ...]
    aar: pd.Series
    caar: pd.Series
    caar_total: float
    t_statistic: float
    t_p_value: float
    patell_z: float
    patell_p_value: float
    bmp_z: float
    bmp_p_value: float
    shared_event_dates: tuple[object, ...]


def estimate_market_model(
    asset_returns: pd.Series | np.ndarray | Sequence[float],
    market_returns: pd.Series | np.ndarray | Sequence[float],
    model: str = "market",
) -> MarketModelFit:
    """Fit a normal-return model on an estimation window.

    Args:
        asset_returns: Asset returns over the estimation window.
        market_returns: Market returns over the same window, same length and
            same order.
        model: One of :data:`NORMAL_RETURN_MODELS`.

    Returns:
        A :class:`MarketModelFit`.

    Raises:
        ValueError: If ``model`` is unknown, the two series differ in length,
            fewer than :data:`MIN_ESTIMATION_OBSERVATIONS` finite pairs survive,
            or the market series has no variation at all under the ``market``
            model (beta would be undefined).
    """
    if model not in NORMAL_RETURN_MODELS:
        raise ValueError(
            f"model must be one of {NORMAL_RETURN_MODELS}, got {model!r}"
        )

    asset = np.asarray(asset_returns, dtype=float).ravel()
    market = np.asarray(market_returns, dtype=float).ravel()
    if asset.size != market.size:
        raise ValueError(
            f"asset and market must be the same length, got {asset.size} and {market.size}"
        )

    keep = np.isfinite(asset) & np.isfinite(market)
    asset, market = asset[keep], market[keep]
    n = asset.size
    if n < MIN_ESTIMATION_OBSERVATIONS:
        raise ValueError(
            f"estimation window needs at least {MIN_ESTIMATION_OBSERVATIONS} "
            f"finite observations, got {n}"
        )

    market_mean = float(market.mean())
    market_sum_squares = float(np.sum((market - market_mean) ** 2))

    if model == "market":
        if market_sum_squares <= 0.0:
            raise ValueError(
                "market returns are constant over the estimation window, so beta "
                "is not identified; use model='mean_adjusted'"
            )
        beta = float(np.sum((market - market_mean) * (asset - asset.mean())) / market_sum_squares)
        alpha = float(asset.mean() - beta * market_mean)
        residuals = asset - (alpha + beta * market)
        dof = n - 2
    elif model == "market_adjusted":
        alpha, beta = 0.0, 1.0
        residuals = asset - market
        dof = n
    else:  # mean_adjusted
        alpha, beta = float(asset.mean()), 0.0
        residuals = asset - alpha
        dof = n - 1

    residual_std = float(np.sqrt(np.sum(residuals**2) / dof)) if dof > 0 else float("nan")

    return MarketModelFit(
        alpha=alpha,
        beta=beta,
        residual_std=residual_std,
        observations=n,
        market_mean=market_mean,
        market_sum_squares=market_sum_squares,
        model=model,
    )


def _patell_scale(fit: MarketModelFit, market_window: np.ndarray) -> np.ndarray:
    """Per-day standard error of an abnormal return, prediction error included.

    A forecast made far from the estimation window's average market return is
    less certain than one made near it, and Patell's correction is exactly that
    term. Dropping it understates the standard error and overstates significance.

    Args:
        fit: The fitted normal-return model.
        market_window: Market returns over the event window.

    Returns:
        Array of standard errors, one per event-window day.
    """
    if fit.model == "market" and fit.market_sum_squares > 0.0:
        prediction_error = (
            1.0
            + 1.0 / fit.observations
            + (market_window - fit.market_mean) ** 2 / fit.market_sum_squares
        )
    elif fit.model == "mean_adjusted":
        prediction_error = np.full(market_window.shape, 1.0 + 1.0 / fit.observations)
    else:  # market_adjusted has no estimated parameter to project
        prediction_error = np.ones(market_window.shape)
    return fit.residual_std * np.sqrt(prediction_error)


def event_study(
    returns: pd.DataFrame,
    market_returns: pd.Series,
    events: Sequence[tuple[str, object]],
    event_window: tuple[int, int] = DEFAULT_EVENT_WINDOW,
    estimation_window: int = DEFAULT_ESTIMATION_WINDOW,
    estimation_gap: int = DEFAULT_ESTIMATION_GAP,
    model: str = "market",
) -> EventStudyResult:
    """Measure the abnormal return around a set of dated events.

    Args:
        returns: Simple returns, rows indexed by date, one column per symbol.
        market_returns: Market returns on the same index. Extra index labels are
            allowed; missing ones are not.
        events: ``(symbol, event_date)`` pairs. ``event_date`` must be present in
            the frame's index, or the nearest earlier row is used and the event
            is reported with the row it snapped to.
        event_window: Inclusive ``(start, end)`` in relative rows, e.g.
            ``(-5, 5)``. ``start`` may be positive if the window opens after the
            event, but must not exceed ``end``.
        estimation_window: Rows used to fit the normal-return model.
        estimation_gap: Rows left between the estimation window and the event
            window so the model cannot see the event.
        model: One of :data:`NORMAL_RETURN_MODELS`.

    Returns:
        An :class:`EventStudyResult`. Events that cannot be measured -- unknown
        symbol, event date before the frame starts, not enough estimation rows,
        an all-NaN window -- appear in ``dropped`` with a reason instead of
        being silently skipped.

    Raises:
        ValueError: If the window bounds are inconsistent, ``estimation_gap`` is
            negative, ``model`` is unknown, the market series does not cover the
            frame's index, or no event at all could be measured.
    """
    start, end = event_window
    if start > end:
        raise ValueError(f"event_window start must be <= end, got {event_window}")
    if estimation_gap < 0:
        raise ValueError(f"estimation_gap must be >= 0, got {estimation_gap}")
    if estimation_window < MIN_ESTIMATION_OBSERVATIONS:
        raise ValueError(
            f"estimation_window must be at least {MIN_ESTIMATION_OBSERVATIONS}, "
            f"got {estimation_window}"
        )
    if model not in NORMAL_RETURN_MODELS:
        raise ValueError(f"model must be one of {NORMAL_RETURN_MODELS}, got {model!r}")
    if not events:
        raise ValueError("events is empty")

    index = returns.index
    missing_market = index.difference(market_returns.index)
    if len(missing_market):
        raise ValueError(
            f"market_returns is missing {len(missing_market)} label(s) present in "
            "returns; align them before calling"
        )
    market_aligned = market_returns.reindex(index)

    relative_days = list(range(start, end + 1))
    window_len = len(relative_days)

    outcomes: list[EventOutcome] = []
    dropped: list[tuple[str, object, str]] = []

    for symbol, event_date in events:
        if symbol not in returns.columns:
            dropped.append((symbol, event_date, "symbol not in returns frame"))
            continue

        position = index.searchsorted(event_date)
        if position >= len(index):
            dropped.append((symbol, event_date, "event date is after the frame ends"))
            continue

        event_start = position + start
        event_end = position + end
        estimation_end = position + start - estimation_gap
        estimation_start = estimation_end - estimation_window

        if estimation_start < 0:
            dropped.append(
                (symbol, event_date, "not enough history before the estimation window")
            )
            continue
        if event_end >= len(index):
            dropped.append((symbol, event_date, "event window runs past the frame end"))
            continue

        asset_estimation = returns[symbol].iloc[estimation_start:estimation_end]
        market_estimation = market_aligned.iloc[estimation_start:estimation_end]
        try:
            fit = estimate_market_model(asset_estimation, market_estimation, model=model)
        except ValueError as exc:
            dropped.append((symbol, event_date, str(exc)))
            continue

        asset_window = returns[symbol].iloc[event_start : event_end + 1].to_numpy(dtype=float)
        market_window = market_aligned.iloc[event_start : event_end + 1].to_numpy(dtype=float)
        if not np.isfinite(asset_window).all() or not np.isfinite(market_window).all():
            dropped.append((symbol, event_date, "event window holds a non-finite return"))
            continue

        expected = fit.alpha + fit.beta * market_window
        abnormal = asset_window - expected
        car = float(abnormal.sum())

        daily_se = _patell_scale(fit, market_window)
        car_se = float(np.sqrt(np.sum(daily_se**2)))
        standardised = car / car_se if car_se > 0 else float("nan")

        outcomes.append(
            EventOutcome(
                symbol=symbol,
                event_date=index[position],
                abnormal_returns=pd.Series(abnormal, index=relative_days, name=symbol),
                car=car,
                car_std_error=car_se,
                standardised_car=standardised,
                fit=fit,
            )
        )

    if not outcomes:
        raise ValueError(
            "no event could be measured; reasons: "
            + "; ".join(f"{s}@{d}: {r}" for s, d, r in dropped)
        )

    n_events = len(outcomes)
    ar_matrix = np.vstack([o.abnormal_returns.to_numpy() for o in outcomes])
    aar = pd.Series(ar_matrix.mean(axis=0), index=relative_days, name="aar")
    caar = pd.Series(np.cumsum(aar.to_numpy()), index=relative_days, name="caar")

    cars = np.array([o.car for o in outcomes])
    if n_events > 1:
        car_sd = float(cars.std(ddof=1))
        t_stat = float(cars.mean() / (car_sd / np.sqrt(n_events))) if car_sd > 0 else float("nan")
        t_p = float(2 * student_t.sf(abs(t_stat), df=n_events - 1)) if np.isfinite(t_stat) else float("nan")
    else:
        t_stat, t_p = float("nan"), float("nan")

    standardised = np.array([o.standardised_car for o in outcomes])
    finite_scar = standardised[np.isfinite(standardised)]

    # Patell: the standardised CARs are unit-variance under the null, up to the
    # t-distribution correction for having estimated the residual variance.
    if finite_scar.size:
        corrections = np.array(
            [
                (o.fit.observations - 2) / (o.fit.observations - 4)
                if o.fit.observations > 4
                else np.nan
                for o in outcomes
                if np.isfinite(o.standardised_car)
            ]
        )
        variance = float(np.nansum(corrections))
        patell_z = float(finite_scar.sum() / np.sqrt(variance)) if variance > 0 else float("nan")
    else:
        patell_z = float("nan")
    patell_p = float(2 * norm.sf(abs(patell_z))) if np.isfinite(patell_z) else float("nan")

    # BMP: cross-sectional variance OF the standardised values, which is what
    # makes it robust to the event itself having raised volatility.
    if finite_scar.size > 1:
        scar_sd = float(finite_scar.std(ddof=1))
        bmp_z = (
            float(finite_scar.mean() / (scar_sd / np.sqrt(finite_scar.size)))
            if scar_sd > 0
            else float("nan")
        )
    else:
        bmp_z = float("nan")
    bmp_p = float(2 * norm.sf(abs(bmp_z))) if np.isfinite(bmp_z) else float("nan")

    seen: dict[object, int] = {}
    for outcome in outcomes:
        seen[outcome.event_date] = seen.get(outcome.event_date, 0) + 1
    shared = tuple(sorted((d for d, c in seen.items() if c > 1), key=str))

    return EventStudyResult(
        event_window=(start, end),
        events=tuple(outcomes),
        dropped=tuple(dropped),
        aar=aar,
        caar=caar,
        caar_total=float(caar.iloc[-1]),
        t_statistic=t_stat,
        t_p_value=t_p,
        patell_z=patell_z,
        patell_p_value=patell_p,
        bmp_z=bmp_z,
        bmp_p_value=bmp_p,
        shared_event_dates=shared,
    )
