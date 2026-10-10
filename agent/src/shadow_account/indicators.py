"""Shared causal price indicators for shadow extraction and scanning."""

import numpy as np
import pandas as pd

RSI_PERIOD = 14


def _wilder_average(values: pd.Series, period: int) -> pd.Series:
    """Seed with a simple mean, then recurse over observed values.

    Args:
        values: Gains or losses, possibly containing missing observations.
        period: Number of observations in the initial seed.

    Returns:
        Aligned averages, with warmup and missing observations left as NaN.
        Missing observations do not update the recursive state.
    """
    result = pd.Series(np.nan, index=values.index, dtype=float)
    positions = np.flatnonzero(values.notna().to_numpy())
    if len(positions) < period:
        return result
    observed = values.iloc[positions].reset_index(drop=True)
    seed = observed.iloc[:period].mean()
    tail = pd.concat([pd.Series([seed]), observed.iloc[period:]], ignore_index=True)
    result.iloc[positions[period - 1 :]] = tail.ewm(alpha=1 / period, adjust=False).mean().to_numpy()
    return result


def compute_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Calculate SMA-seeded Wilder RSI without future bars.

    Args:
        close: Close prices in chronological order.
        period: Positive number of observed deltas used for warmup.

    Returns:
        RSI aligned with close, NaN during warmup or at a missing delta.
        Flat prices retain the existing undefined (NaN) convention.

    Raises:
        ValueError: If period is not a positive integer.
    """
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("period must be a positive integer")
    delta = close.diff()
    avg_gain = _wilder_average(delta.clip(lower=0), period)
    avg_loss = _wilder_average((-delta).clip(lower=0), period)
    return 100 - 100 / (1 + avg_gain / avg_loss)
