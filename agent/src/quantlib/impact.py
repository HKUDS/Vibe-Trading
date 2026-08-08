"""Market-impact and slippage models for backtest execution.

Four models, ordered by how much of the order book they claim to know:

========================= ================================== =====================
Model                     Impact                             Use when
========================= ================================== =====================
:func:`fixed_slippage`    constant ``bps``                   order < 0.5% of ADV
:func:`linear_impact`     ``coeff * V / ADV``                order 0.5-5% of ADV
:func:`sqrt_impact`       ``eta * sigma * sqrt(V / ADV)``    order > 5% of ADV
:func:`delayed_execution` shifts a signal forward in time    always, for signal lag
========================= ================================== =====================

All three price models compute a non-negative impact and push the fill price
*against* the trader -- up when buying, down when selling.

The two size-aware models, :func:`linear_impact` and :func:`sqrt_impact`, are
additionally monotone non-decreasing in order size and return the untouched price
at zero size. :func:`fixed_slippage` takes no size at all: it charges its ``bps``
on every fill regardless of how small, which is the whole point of a fixed model
and the reason it is only appropriate below roughly 0.5% of ADV.

Every function here is scalar-only. Passing a numpy array or a pandas Series where
a ``float`` is documented raises rather than broadcasting.

These are backtest primitives. Nothing here places, routes or prices a live order.

Note on naming: the square-root model is frequently labelled "Almgren-Chriss" and
is indeed the impact term from that literature, but this module does **not**
implement Almgren-Chriss optimal execution -- there is no trading trajectory, no
permanent/temporary impact split and no risk-aversion parameter. Call it what it
is: a square-root impact function.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike

#: Default fixed slippage in basis points (1bp = 0.01%).
DEFAULT_SLIPPAGE_BPS = 5.0

#: Default linear-impact coefficient; 0.05-0.2 is the usual calibrated range.
DEFAULT_LINEAR_IMPACT_COEFF = 0.1

#: Default square-root impact elasticity; 0.3-0.8 is the usual calibrated range.
DEFAULT_SQRT_IMPACT_ETA = 0.5

#: Default execution lag in bars. 1 bar matches the China A-share T+1 rule.
DEFAULT_DELAY_BARS = 1

#: Basis points in one unit (100%).
_BPS_PER_UNIT = 10_000.0


def _check_order(price: ArrayLike, direction: int) -> np.ndarray:
    """Validate the price and side shared by every price-impact model.

    Args:
        price: Reference price before impact; scalar or array-like.
        direction: 1 to buy, -1 to sell.

    Returns:
        ``price`` as a float array (0-d for a scalar input).

    Raises:
        ValueError: If any ``price`` is not strictly positive, or if
            ``direction`` is anything other than 1 or -1. Direction multiplies
            the impact, so a value such as 2 would silently double the modelled
            cost.
    """
    prices = np.asarray(price, dtype=float)
    if not np.all(prices > 0.0):
        raise ValueError(f"price must be strictly positive, got {price!r}")
    if direction not in (1, -1):
        raise ValueError(f"direction must be 1 (buy) or -1 (sell), got {direction!r}")
    return prices


def _participation_rate(volume_traded: ArrayLike, adv: ArrayLike) -> np.ndarray:
    """Return the order size as a fraction of average daily volume.

    Args:
        volume_traded: Order size, in the same unit as ``adv``.
        adv: Average daily volume, strictly positive.

    Returns:
        ``volume_traded / adv``, broadcast over both arguments.

    Raises:
        ValueError: If any ``volume_traded`` is negative or any ``adv`` is not
            strictly positive. A zero ``adv`` means the instrument does not
            trade, for which no impact model has an answer.
    """
    volumes = np.asarray(volume_traded, dtype=float)
    advs = np.asarray(adv, dtype=float)
    if not np.all(volumes >= 0.0):
        raise ValueError(f"volume_traded must be non-negative, got {volume_traded!r}")
    if not np.all(advs > 0.0):
        raise ValueError(f"adv must be strictly positive, got {adv!r}")
    return volumes / advs


def _fill(prices: np.ndarray, direction: int, impact: np.ndarray) -> float | np.ndarray:
    """Apply a relative impact to a price and return the fill.

    Args:
        prices: Validated reference prices as a float array.
        direction: 1 to buy, -1 to sell.
        impact: Relative impact, same shape or broadcastable.

    Returns:
        The fill price -- a float for scalar input, an ndarray otherwise, so a
        scalar call never has to unwrap a 0-d array.

    Raises:
        ValueError: If the impact is large enough to drive a sell fill to zero
            or below. Both functions reject a non-positive input price, so
            returning one is incoherent: a sell filling at a negative price
            books a nonsensical profit. An order that large is outside the
            model's calibrated domain and the honest answer is a refusal, not
            an extrapolation.
    """
    fill = prices * (1.0 + direction * impact)
    if not np.all(fill > 0.0):
        raise ValueError(
            "impact drives the fill price to zero or below "
            f"(max relative impact {float(np.max(impact)):.4g}); the order is "
            "outside the model's domain -- split it or use a fill model that "
            "accounts for depth"
        )
    return float(fill) if fill.ndim == 0 else fill


def fixed_slippage(price: float, direction: int, bps: float = DEFAULT_SLIPPAGE_BPS) -> float:
    """Apply a constant basis-point slippage to a fill price.

    The cheapest model, and adequate whenever the order is small enough that it
    does not move the book -- roughly under 0.5% of average daily volume.

    Args:
        price: Reference price before slippage.
        direction: 1 to buy, -1 to sell.
        bps: Slippage in basis points. Defaults to :data:`DEFAULT_SLIPPAGE_BPS`.

    Returns:
        The fill price after slippage: worse than ``price`` for both sides.

    Raises:
        ValueError: If ``price`` is not strictly positive, ``direction`` is not 1
            or -1, or ``bps`` is negative.
    """
    prices = _check_order(price, direction)
    rates = np.asarray(bps, dtype=float)
    if not np.all(rates >= 0.0):
        raise ValueError(f"bps must be non-negative, got {bps!r}")
    return _fill(prices, direction, rates / _BPS_PER_UNIT)


def linear_impact(
    price: float,
    direction: int,
    volume_traded: float,
    adv: float,
    impact_coeff: float = DEFAULT_LINEAR_IMPACT_COEFF,
) -> float:
    """Apply market impact proportional to the participation rate.

    Impact is ``impact_coeff * volume_traded / adv``. Marginal impact is constant,
    which overstates the cost of very large orders; prefer :func:`sqrt_impact`
    once the order exceeds roughly 5% of average daily volume.

    Args:
        price: Reference price before impact.
        direction: 1 to buy, -1 to sell.
        volume_traded: Order size, in the same unit as ``adv``.
        adv: Average daily volume, strictly positive.
        impact_coeff: Impact coefficient. Defaults to
            :data:`DEFAULT_LINEAR_IMPACT_COEFF`.

    Returns:
        The fill price after impact.

    Raises:
        ValueError: If ``price`` is not strictly positive, ``direction`` is not 1
            or -1, ``volume_traded`` is negative, ``adv`` is not strictly
            positive, or ``impact_coeff`` is negative.
    """
    prices = _check_order(price, direction)
    coeffs = np.asarray(impact_coeff, dtype=float)
    if not np.all(coeffs >= 0.0):
        raise ValueError(f"impact_coeff must be non-negative, got {impact_coeff!r}")
    return _fill(prices, direction, coeffs * _participation_rate(volume_traded, adv))


def sqrt_impact(
    price: float,
    direction: int,
    volume_traded: float,
    adv: float,
    volatility: float,
    eta: float = DEFAULT_SQRT_IMPACT_ETA,
) -> float:
    """Apply square-root market impact, the best empirically supported form.

    Impact is ``eta * volatility * sqrt(volume_traded / adv)``. Marginal impact
    falls as the order grows, which matches observed execution data far better
    than the linear form.

    This is the impact term familiar from the Almgren-Chriss literature; it is not
    Almgren-Chriss optimal execution, which additionally solves for a trading
    trajectory under a risk-aversion penalty. No trajectory is computed here.

    Args:
        price: Reference price before impact.
        direction: 1 to buy, -1 to sell.
        volume_traded: Order size, in the same unit as ``adv``.
        adv: Average daily volume, strictly positive.
        volatility: Daily return volatility as a decimal fraction, non-negative.
        eta: Impact elasticity. Defaults to :data:`DEFAULT_SQRT_IMPACT_ETA`.

    Returns:
        The fill price after impact.

    Raises:
        ValueError: If ``price`` is not strictly positive, ``direction`` is not 1
            or -1, ``volume_traded`` is negative, ``adv`` is not strictly
            positive, or ``volatility`` or ``eta`` is negative.
    """
    prices = _check_order(price, direction)
    vols = np.asarray(volatility, dtype=float)
    etas = np.asarray(eta, dtype=float)
    if not np.all(vols >= 0.0):
        raise ValueError(f"volatility must be non-negative, got {volatility!r}")
    if not np.all(etas >= 0.0):
        raise ValueError(f"eta must be non-negative, got {eta!r}")
    impact = etas * vols * np.sqrt(_participation_rate(volume_traded, adv))
    return _fill(prices, direction, impact)


def delayed_execution(signal_series: pd.Series, delay_bars: int = DEFAULT_DELAY_BARS) -> pd.Series:
    """Shift a signal forward to model the lag between decision and fill.

    A signal computed from a bar's data cannot be traded on that same bar. Shifting
    it forward is what keeps a backtest honest.

    Args:
        signal_series: Signal indexed in chronological order.
        delay_bars: Bars to delay by. Defaults to :data:`DEFAULT_DELAY_BARS`
            (T+1). 0 means same-bar execution.

    Returns:
        The signal shifted forward by ``delay_bars``, with the leading positions
        set to NaN by the shift.

    Raises:
        TypeError: If ``signal_series`` is not a :class:`pandas.Series`.
        ValueError: If ``delay_bars`` is negative. A negative shift would pull
            future signal values into the past, which is look-ahead bias and
            silently inflates every backtest that contains it.
    """
    if not isinstance(signal_series, pd.Series):
        raise TypeError(f"signal_series must be a pandas Series, got {type(signal_series).__name__}")
    if delay_bars < 0:
        raise ValueError(f"delay_bars must be non-negative; a negative shift is look-ahead bias, got {delay_bars!r}")
    return signal_series.shift(delay_bars)
