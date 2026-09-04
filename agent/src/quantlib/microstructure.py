"""Market microstructure signals: VPIN, Roll's effective spread, and Amihud illiquidity.

Implements institutional market microstructure indicators:
  1. Volume-Synchronized Probability of Toxicity (VPIN - Easley et al. 2012)
  2. Roll's (1984) effective bid-ask spread estimator from serial covariance
  3. Amihud's (2002) price impact / illiquidity ratio
  4. Kyle's (1985) price impact lambda
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd

__all__ = [
    "amihud_illiquidity",
    "kyles_lambda",
    "roll_effective_spread",
    "vpin",
]


def roll_effective_spread(prices: Sequence[float] | np.ndarray | pd.Series) -> float:
    """Calculate Roll's (1984) effective spread estimator from serial price changes.

    Roll's model: s = 2 * sqrt(-cov(ΔP_t, ΔP_{t-1})) if cov < 0, else 0.0.

    Args:
        prices: Sequence of transaction or closing prices.

    Returns:
        Estimated effective dollar spread (non-negative float).
    """
    p = np.asarray(prices, dtype=float)
    if len(p) < 4:
        raise ValueError("prices sequence must have at least 4 points to compute serial covariance")
    dp = np.diff(p)
    dp_t = dp[1:]
    dp_t_minus_1 = dp[:-1]
    cov = float(np.cov(dp_t, dp_t_minus_1)[0, 1])
    if cov < 0.0:
        return float(2.0 * math.sqrt(-cov))
    return 0.0


def amihud_illiquidity(
    returns: Sequence[float] | np.ndarray | pd.Series,
    dollar_volumes: Sequence[float] | np.ndarray | pd.Series,
) -> float:
    """Calculate Amihud's (2002) illiquidity ratio: mean(|R_t| / DollarVolume_t).

    Measures the average price response per dollar of trading volume.

    Args:
        returns: Array of asset returns (decimal).
        dollar_volumes: Array of traded dollar volumes (> 0).

    Returns:
        Amihud illiquidity metric (positive float).
    """
    r = np.asarray(returns, dtype=float)
    v = np.asarray(dollar_volumes, dtype=float)
    if r.shape != v.shape or len(r) == 0:
        raise ValueError("returns and dollar_volumes must be non-empty and have matching shapes")
    valid_mask = (v > 0.0) & ~np.isnan(r) & ~np.isnan(v)
    if not np.any(valid_mask):
        return float("nan")
    ratios = np.abs(r[valid_mask]) / v[valid_mask]
    return float(np.mean(ratios))


def kyles_lambda(
    price_changes: Sequence[float] | np.ndarray | pd.Series,
    signed_order_flow: Sequence[float] | np.ndarray | pd.Series,
) -> float:
    """Estimate Kyle's (1985) price impact coefficient lambda from linear regression.

    ΔP_t = lambda * OrderFlow_t + epsilon_t

    Args:
        price_changes: Array of price differences ΔP_t.
        signed_order_flow: Array of signed trade volumes (+ for buy, - for sell).

    Returns:
        Kyle's lambda price impact slope.
    """
    dp = np.asarray(price_changes, dtype=float)
    flow = np.asarray(signed_order_flow, dtype=float)
    if dp.shape != flow.shape or len(dp) < 2:
        raise ValueError("price_changes and signed_order_flow must match with >= 2 observations")
    denom = float(np.sum(flow**2))
    if denom == 0.0:
        return 0.0
    return float(np.sum(dp * flow) / denom)


def vpin(
    buy_volume: Sequence[float] | np.ndarray,
    sell_volume: Sequence[float] | np.ndarray,
    bucket_size: float,
    n_buckets: int = 50,
) -> np.ndarray:
    """Compute Volume-Synchronized Probability of Toxicity (VPIN - Easley et al. 2012).

    VPIN = sum_{i=t-N+1}^t |V_B,i - V_S,i| / (N * V)
    aggregating trade volume into standardized constant-volume buckets of size V.

    Args:
        buy_volume: Array of buy trade volumes per time bar.
        sell_volume: Array of sell trade volumes per time bar.
        bucket_size: Standardized volume bucket size V (> 0).
        n_buckets: Number of volume buckets N in rolling window (default=50).

    Returns:
        1-D ndarray of VPIN values in [0, 1] for completed volume buckets.
    """
    vb = np.asarray(buy_volume, dtype=float)
    vs = np.asarray(sell_volume, dtype=float)
    if vb.shape != vs.shape or len(vb) == 0:
        raise ValueError("buy_volume and sell_volume must have matching non-empty shapes")
    if bucket_size <= 0.0:
        raise ValueError(f"bucket_size must be positive, got {bucket_size}")
    if n_buckets <= 0:
        raise ValueError(f"n_buckets must be positive, got {n_buckets}")

    # Accumulate trades into constant-volume buckets of size V
    bucket_imbalances: list[float] = []
    curr_buy = 0.0
    curr_sell = 0.0

    for b, s in zip(vb, vs):
        rem_b = float(b)
        rem_s = float(s)

        while (rem_b + rem_s) > 0.0:
            curr_filled = curr_buy + curr_sell
            space = bucket_size - curr_filled
            total_bar = rem_b + rem_s

            if total_bar <= space:
                curr_buy += rem_b
                curr_sell += rem_s
                rem_b = 0.0
                rem_s = 0.0
            else:
                # Fill the remaining bucket space proportionally
                frac_b = rem_b / total_bar
                frac_s = rem_s / total_bar
                take_b = space * frac_b
                take_s = space * frac_s

                curr_buy += take_b
                curr_sell += take_s
                rem_b -= take_b
                rem_s -= take_s

            if (curr_buy + curr_sell) >= bucket_size - 1e-9:
                bucket_imbalances.append(abs(curr_buy - curr_sell))
                curr_buy = 0.0
                curr_sell = 0.0

    if not bucket_imbalances:
        return np.array([], dtype=float)

    imbalances = pd.Series(bucket_imbalances)
    rolling_imb = imbalances.rolling(window=n_buckets, min_periods=1).sum()
    denom = pd.Series(range(1, len(bucket_imbalances) + 1)).clip(upper=n_buckets) * bucket_size
    vpin_series = rolling_imb / denom
    return np.clip(vpin_series.to_numpy(), 0.0, 1.0)
