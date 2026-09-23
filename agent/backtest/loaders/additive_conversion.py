"""Convert additive qfq series to the multiplicative (ratio) convention.

A-share forward-adjusted prices from Tencent, Eastmoney and AKShare are
dividend-ADDITIVE: between corporate actions ``qfq - raw`` is a constant
offset, and each down-step at an ex-date is the cash dividend per share
(HKUDS/Vibe-Trading#1541). A return computed on those levels is not a total
return (the owner measured 600519.SH 2019 buy-and-hold at +184.07% additive
against +100.43% multiplicative), and old levels can even go negative.

The offsets are enough to recover the multiplicative series: at each step the
factor is ``(prev_raw_close - dividend) / prev_raw_close``, and the cumulative
product scales raw bars onto the 前复权 ratio basis, the same convention
``cn_adjust.apply_qfq`` uses for Tushare factors. Two consequences of the
construction to know before reading levels off the result:

- The series is anchored at the window's END (bars after the last in-window
  action keep ratio 1), so absolute levels depend on the requested range;
  returns are unaffected. Windows that cross a 送转 (bonus-share) event have
  offsets that drift with the price level by construction, and this module
  refuses them rather than converting on a wrong basis.
- A window with no corporate action inside it has nothing to convert; the
  caller keeps today's series and its static stamp instead of an identity
  relabel.

Any inconsistency (misaligned calendars, offsets that are not plateaus, a
non-positive or oversized dividend) returns ``None`` so the caller keeps the
additive series, stamp and warning instead of shipping a bad conversion.
"""

from __future__ import annotations

import pandas as pd

# Offsets come from exact float subtraction, but allow cents-level slack when
# grouping them into plateaus so a binary-representation wobble cannot split
# one corporate-action segment into two.
_OFFSET_TOL = 1e-6

# A one-bar plateau inside (or at the edge of) a longer level is a quote
# wobble, not a dividend: fold it only when the neighboring level(s) match
# within this tolerance. Anything else that short cannot be classified and
# refuses the window (a wrong series with a clean stamp is the worst outcome).
_WOBBLE_TOL = 0.05


def _plateau_spans(offset: pd.Series) -> list[tuple[int, int, float]] | None:
    """Group the offset series into [start, end) spans of one constant value.

    One-bar spans are folded into a matching neighbor within ``_WOBBLE_TOL``
    (quote wobble); a one-bar span that cannot be classified that way returns
    None, since dropping a step we cannot classify would mint a wrong series
    with a clean stamp.
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

    # Fold one-bar wobbles into the level they deviate from.
    while True:
        foldable_idx = None
        for i, (span_start, span_end, value) in enumerate(spans):
            if span_end - span_start != 1:
                continue
            prev_value = spans[i - 1][2] if i > 0 else None
            next_value = spans[i + 1][2] if i + 1 < len(spans) else None
            # Interior wobble: both neighbors agree with each other.
            if (
                prev_value is not None
                and next_value is not None
                and abs(prev_value - next_value) <= _WOBBLE_TOL
                and abs(value - prev_value) <= _WOBBLE_TOL
            ):
                foldable_idx = i
                break
            # Edge wobble: the lone bar at either end matches its neighbor.
            if i == 0 and next_value is not None and abs(value - next_value) <= _WOBBLE_TOL:
                foldable_idx = i
                break
            if i == len(spans) - 1 and prev_value is not None and abs(value - prev_value) <= _WOBBLE_TOL:
                foldable_idx = i
                break
        if foldable_idx is None:
            # Any one-bar plateau left cannot be classified as noise; refuse
            # rather than guess.
            if any(end - start == 1 for start, end, _ in spans):
                return None
            break
        del spans[foldable_idx]
        # Re-join spans split by the wobble (same level now adjacent).
        joined: list[tuple[int, int, float]] = []
        for span in spans:
            if joined and abs(span[2] - joined[-1][2]) <= _OFFSET_TOL:
                joined[-1] = (joined[-1][0], span[1], joined[-1][2])
            else:
                joined.append(span)
        spans = joined
    return spans


def convert_additive_to_multiplicative(raw: pd.DataFrame, additive: pd.DataFrame) -> pd.DataFrame | None:
    """Convert an additive qfq frame to the multiplicative convention.

    Args:
        raw: Unadjusted OHLCV bars (``close`` required), ascending date index.
        additive: The same window's additive-adjusted bars.

    Returns:
        The converted frame (OHLC scaled by the cumulative ratio, ``volume``
        divided by it, other columns untouched), or ``None`` when the inputs
        cannot support a trustworthy conversion — including a window with no
        corporate action in it, which stays as served today.
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
    if spans is None:
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

    # No in-window corporate action: there is nothing to convert, and an
    # identity relabel would only misstate the stamp.
    if not factors:
        return None

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
