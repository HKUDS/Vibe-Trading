"""Convert additive qfq series to the multiplicative (ratio) convention.

A-share forward-adjusted prices from Tencent, Eastmoney and AKShare are
dividend-ADDITIVE: between corporate actions ``qfq - raw`` is a constant
offset, and each down-step at an ex-date is the cash dividend per share
(HKUDS/Vibe-Trading#1541). A return computed on those levels is not a total
return (the owner measured 600519.SH 2019 buy-and-hold at +184.07% additive
against +100.43% multiplicative), and old levels can even go negative.

The offsets are enough to recover the multiplicative series: at each step the
factor is ``(prev_raw_close - dividend) / prev_raw_close``, and the cumulative
product scales raw bars onto the 前复权 ratio basis anchored at the last bar,
the same convention ``cn_adjust.apply_qfq`` uses for Tushare factors. Any
inconsistency (misaligned calendars, offsets that are not plateaus, a
non-positive or oversized dividend) returns ``None`` so the caller keeps the
additive series, stamp and warning instead of shipping a bad conversion.
"""

from __future__ import annotations

import pandas as pd

# Offsets come from exact float subtraction, but allow cents-level slack when
# grouping them into plateaus so a binary-representation wobble cannot split
# one corporate-action segment into two.
_OFFSET_TOL = 1e-6

# Adjacent plateaus closer than this are the same segment: one bar's rounding
# noise must not mint a fake dividend (a 2016 first bar wobbles 0.02).
_PLATEAU_MERGE_TOL = 0.05


def _plateau_spans(offset: pd.Series) -> list[tuple[int, int, float]] | None:
    """Group the offset series into [start, end) spans of one constant value.

    Returns None when the offsets vary bar to bar (not plateaus), which means
    the series is not dividend-additive and there is nothing to convert.
    """
    spans: list[tuple[int, int, float]] = []
    start = 0
    current = float(offset.iloc[0])
    for i in range(1, len(offset)):
        value = float(offset.iloc[i])
        if abs(value - current) > _OFFSET_TOL:
            spans.append((start, i, current))
            start = i
            current = value
    spans.append((start, len(offset), current))
    # Fold sub-noise steps back into their segment: a boundary whose offset
    # moves by less than a few cents is a rounding artifact, not an action.
    merged: list[tuple[int, int, float]] = []
    for span in spans:
        if merged and abs(span[2] - merged[-1][2]) < _PLATEAU_MERGE_TOL:
            merged[-1] = (merged[-1][0], span[1], merged[-1][2])
        else:
            merged.append(span)
    return merged


def convert_additive_to_multiplicative(
    raw: pd.DataFrame, additive: pd.DataFrame
) -> pd.DataFrame | None:
    """Convert an additive qfq frame to the multiplicative convention.

    Args:
        raw: Unadjusted OHLCV bars (``close`` required), ascending date index.
        additive: The same window's additive-adjusted bars.

    Returns:
        The converted frame (OHLC scaled by the cumulative ratio, ``volume``
        divided by it, other columns untouched), or ``None`` when the inputs
        cannot support a trustworthy conversion.
    """
    if raw is None or additive is None or raw.empty or additive.empty:
        return None
    if "close" not in raw.columns or "close" not in additive.columns:
        return None

    joined = raw.join(additive, how="inner", lsuffix="_raw", rsuffix="_adj")
    # Every raw bar must be covered by the additive series; a partial window
    # would silently convert only part of the history.
    if len(joined) != len(raw) or len(joined) != len(additive):
        return None

    offset = joined["close_adj"] - joined["close_raw"]
    spans = _plateau_spans(offset)
    if not spans:
        return None
    # A genuine additive series steps a handful of times over hundreds of
    # bars (the owner measured five offsets over 500 bars). One-bar plateaus
    # dominating the window are not dividends; they are the signature of a
    # ratio-adjusted series, where qfq - raw drifts with the price level, and
    # converting that would double-adjust.
    single_bar_spans = sum(1 for start, end, _ in spans if end - start == 1)
    if len(spans) > 1 and single_bar_spans * 2 > len(spans):
        return None

    # Factor per boundary between plateau k and k+1. The offset steps toward
    # zero at each ex-date, and the step size is the cash dividend per share.
    factors: list[tuple[int, float]] = []  # (first bar of plateau k+1, factor)
    for k in range(len(spans) - 1):
        _, end_k, off_k = spans[k]
        _, _, off_next = spans[k + 1]
        dividend = off_next - off_k  # offset rises toward 0 on the ex-date
        prev_raw_close = float(joined["close_raw"].iloc[end_k - 1])
        if prev_raw_close <= 0:
            return None
        if dividend <= 0 or dividend >= prev_raw_close:
            # A non-positive step is not a dividend, and a dividend at or
            # above the price is a data anomaly, not an adjustment.
            return None
        factors.append((end_k, (prev_raw_close - dividend) / prev_raw_close))

    # Cumulative ratio per bar, anchored at the last bar (前复权): bars after
    # the last corporate action keep ratio 1, and each step multiplies
    # everything before it by that action's factor.
    ratio = pd.Series(1.0, index=joined.index)
    for first_bar_after, factor in factors:
        ratio.iloc[:first_bar_after] *= factor
    if (ratio <= 0).any():
        return None

    out = raw.copy()
    for col in ("open", "high", "low", "close"):
        if col in out.columns:
            out[col] = out[col] * ratio
    if "volume" in out.columns:
        out["volume"] = out["volume"] / ratio
    return out
