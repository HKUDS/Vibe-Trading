"""Regime detector v0 — bull / bear / neutral.

Inputs:
- BTC daily close (need warmup ≥ ema_window days before evaluation start)
- Funding rate (any granularity)

Rules (default ema_window=200, vol_window=30, funding_window=30):
- price > EMA and EMA slope > 0 → bull
- price < EMA and EMA slope < 0 → bear
- otherwise → neutral

Funding mean sign overrides:
- If funding_mean > +0.0003 (sustained positive, mania) AND label is "bear" → flip to neutral
  (positive funding inconsistent with bear — protects against early bottoms / dead-cat traps)
- If funding_mean < -0.0003 (sustained negative, capitulation) AND label is "bull" → flip to neutral
"""

from __future__ import annotations

import pandas as pd


def compute_regime(
    daily_close: pd.Series,
    funding_rate: pd.Series | None = None,
    ema_window: int = 200,
    slope_window: int = 20,
    funding_window_hours: int = 30 * 24,
    funding_mania_threshold: float = 3e-4,
    bear_persistence_days: int = 20,
    bear_persistence_threshold: float = 0.55,
) -> pd.DataFrame:
    """Compute daily regime labels.

    Args:
        daily_close: BTC daily close (tz-naive UTC index, ≥ ema_window days of warmup).
        funding_rate: optional funding history at native interval.
        ema_window: EMA span (default 200).
        slope_window: bars to compute EMA slope sign over (default 20 → ~month).
        funding_window_hours: funding rolling mean window in hours (default 30d).
        funding_mania_threshold: |funding mean| above this flips regime to neutral.

    Returns:
        DataFrame indexed by daily timestamp with columns: ema, slope, regime, funding_mean
    """
    s = daily_close.sort_index().dropna()
    ema = s.ewm(span=ema_window, adjust=False).mean()
    slope = ema.diff(slope_window)

    above = s > ema
    pos_slope = slope > 0

    regime = pd.Series("neutral", index=s.index, dtype=object)
    regime[above & pos_slope] = "bull"
    regime[(~above) & (~pos_slope)] = "bear"

    funding_mean = pd.Series(index=s.index, dtype=float)
    if funding_rate is not None and not funding_rate.empty:
        fr = funding_rate.sort_index()
        if hasattr(fr.index, "tz") and fr.index.tz is not None:
            fr = fr.copy()
            fr.index = fr.index.tz_convert(None)
        roll = fr.rolling(funding_window_hours, min_periods=max(1, funding_window_hours // 4)).mean()
        funding_mean = roll.reindex(s.index, method="ffill")

        mania = funding_mean > funding_mania_threshold
        capit = funding_mean < -funding_mania_threshold
        regime[(regime == "bear") & mania] = "neutral"
        regime[(regime == "bull") & capit] = "neutral"

    if bear_persistence_days > 0:
        is_bear = (regime == "bear").astype(int)
        rolling_bear_share = is_bear.rolling(bear_persistence_days, min_periods=1).mean()
        bear_confirmed = rolling_bear_share >= bear_persistence_threshold
        regime_v1 = regime.copy()
        regime_v1[(regime == "bear") & (~bear_confirmed)] = "neutral"
        regime = regime_v1

    return pd.DataFrame(
        {"ema": ema, "slope": slope, "funding_mean": funding_mean, "regime": regime}
    )


def daily_close_from_hourly(df: pd.DataFrame, col: str = "close") -> pd.Series:
    """Resample hourly OHLCV close to daily UTC close."""
    return df[col].resample("1D").last().dropna()
