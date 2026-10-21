"""Market-agnostic split detector for ``paper_trade_step`` (Step 4 / T4).

R6 / AM-2 / VD-6 (frozen, G1-approved): hk/us serve RAW (unadjusted) prices,
so a split ex-date can break the ledger. All three markets now use raw
execution bars. This module identifies candidate discontinuities only;
OHLC/volume is not authoritative corporate-action evidence. The engine
refuses a split-like candidate without changing holdings.

Triple gate for a CLEAN hit (all three must hold; exact rational arithmetic
via ``Fraction``/``Decimal`` — never the built-in rounding function, VD-9):

1. **Price gate** — the close-to-close ratio ``close_after / close_before``
   matches ``1 / mult`` for some frozen clean qty multiplier
   ``mult ∈ {2,3,4,5,10,3/2} ∪ {1/2,1/3,1/4,1/5,1/10,2/3}`` within
   :data:`PRICE_RATIO_REL_TOL` (1e-3 relative).
2. **Volume gate** — the volume ratio ``volume_after / volume_before`` equals
   the SAME multiple ``mult`` (price 1/4 ⇒ volume 4x — the same-direction
   confirmation VD-6 requires) within :data:`VOLUME_RATIO_REL_TOL`.
3. **NAV gate** — post-adjustment NAV continuity against the prior close
   holds within ±0.01% (:data:`NAV_CONTINUITY_REL_TOL` = 1e-4 relative, the
   R6-1 frozen bound): ``|qty·mult·close_after − qty·close_before| ≤
   1e-4 · qty·close_before``.  For qty > 0 the qty cancels, so this is the
   price gate restated on position value; qty = 0 passes trivially (no
   position to preserve).  The gate is computed with the injected qty to
   honor the contract signature (input = bar series + current position qty).

A boundary is a CANDIDATE discontinuity only when the price ratio falls
outside the neutral band bounded by the smallest frozen split magnitudes
(``ratio ≤ 2/3`` or ``ratio ≥ 3/2``; ``ratio == 1`` is inside the band).  A
candidate that is NOT a clean hit is UNRESOLVED — the ratio is never guessed
and the boundary is never silently passed (fail-closed, R6-3): the engine
rejects that symbol's orders for the day ``corporate_action_unresolved``.

Note 2 (APPROVAL §3, VT obligation): only boundaries whose AFTER-date is a
SIMULATED day in ``[from_date, to_date]`` are scanned; the BEFORE bar may sit
in the K=120 lookback (required when ``from_date`` itself is the ex-date).  A
historical discontinuity wholly before ``from_date`` never triggers an event
or a rejection — otherwise a stale non-clean action would keep mis-rejecting
the symbol for the whole window.

Cash dividends are NEVER detected heuristically (R6-5: a raw series has no
clean ratio to anchor; fabricating a dividend cash adjustment is worse than
disclosing the price-return caliber, AM-12).  Determinism (R1-1): no clock,
no randomness, no I/O; every input is injected.  Provenance form note: the
internal ``corporate_actions[]`` entries carry ``detected`` as a bool and
``ratio`` as a string; the DRAFT wire skeleton types both as strings — T5
owns the wire surface and reconciles the skeleton at finalization (the
skeleton file is not touched here).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import TYPE_CHECKING, Any, Collection, Mapping, Sequence

if TYPE_CHECKING:
    from .data import MarketDataResult, SymbolData
    from .schema import Position

__all__ = [
    "CLEAN_QTY_MULTIPLIERS",
    "NAV_CONTINUITY_REL_TOL",
    "PRICE_RATIO_REL_TOL",
    "VOLUME_RATIO_REL_TOL",
    "CorporateActionPlan",
    "EMPTY_PLAN",
    "SplitEvent",
    "build_plan",
    "classify_boundary",
    "detect_symbol",
    "merge_unresolved",
    "ratio_label",
]

#: Frozen clean qty-multiplier set (R6-1 / VD-6): {2,3,4,5,10,3/2} ∪ their
#: reciprocals.  A 4:1 split has qty multiplier 4 (price ratio 1/4, volume
#: ratio 4); a 1:4 reverse split has qty multiplier 1/4.  The set is closed
#: under reciprocation, so the clean price ratios are the same 12 values.
CLEAN_QTY_MULTIPLIERS: tuple[Fraction, ...] = (
    Fraction(2), Fraction(3), Fraction(4), Fraction(5), Fraction(10), Fraction(3, 2),
    Fraction(1, 2), Fraction(1, 3), Fraction(1, 4), Fraction(1, 5), Fraction(1, 10), Fraction(2, 3),
)

# Neutral band bounds = the smallest frozen split magnitudes expressed as
# price ratios (qty 3/2 ⇒ price 2/3; qty 2/3 ⇒ price 3/2).  A candidate
# discontinuity is a price ratio at or beyond either bound.
_BAND_LOW = Fraction(2, 3)
_BAND_HIGH = Fraction(3, 2)

#: Documented relative tolerances (exact rationals; the built-in rounding
#: function is never used on any path, VD-9).  The price gate (1e-3) absorbs
#: cent-quote quantization of the ex-date reference price (0.005/P ≤ 1e-3 for
#: post-split prices P ≥ 5.00; cheaper lines fail closed); the NAV gate is the
#: contract-frozen ±0.01% (R6-1) and is the binding confirmation for held
#: positions; volume is looser (1e-2) because share counts are noisier than
#: prices — it only confirms the same-direction multiple.
PRICE_RATIO_REL_TOL = Fraction(1, 1000)
VOLUME_RATIO_REL_TOL = Fraction(1, 100)
NAV_CONTINUITY_REL_TOL = Fraction(1, 10000)

_ZERO_DEC = Decimal(0)

KIND_CLEAN = "clean"
KIND_UNRESOLVED = "unresolved"
KIND_NONE = "none"


@dataclass(frozen=True, slots=True)
class BoundaryVerdict:
    """One boundary classification (pure detector output)."""

    kind: str  # KIND_CLEAN | KIND_UNRESOLVED | KIND_NONE
    qty_multiplier: Fraction | None = None  # clean ratio; None unless clean
    observed_ratio: Decimal | None = None  # close_after/close_before (a fact)


@dataclass(frozen=True, slots=True)
class SplitEvent:
    """A detected event on one simulated day (clean or unresolved)."""

    symbol: str
    date: str  # ex-date = the AFTER bar's date (a simulated day, note 2)
    detected: bool  # True = ratio candidate, not authority to adjust a ledger
    qty_multiplier: Fraction | None  # clean ratio; None when unresolved
    observed_ratio: Decimal  # observed close_after/close_before (provenance fact)


@dataclass(frozen=True, slots=True)
class CorporateActionPlan:
    """Assembled plan the engine threads into the day loop (T4)."""

    clean_by_day: Mapping[str, tuple[SplitEvent, ...]]
    unresolved_by_day: Mapping[str, tuple[str, ...]]
    warnings: tuple[str, ...]
    provenance: tuple[dict[str, Any], ...]


#: cn_a / no-event plan (the engine uses it verbatim for the exempt market).
EMPTY_PLAN = CorporateActionPlan(clean_by_day={}, unresolved_by_day={}, warnings=(), provenance=())


def _positive_finite(value: float) -> bool:
    return math.isfinite(value) and value > 0.0


def _fraction(value: float) -> Fraction:
    # Decimal(str(x)) is the VD-9 money-path entry conversion; Fraction of it
    # is the exact rational of the shortest round-trip decimal (no binary
    # float error, no built-in rounding function).
    return Fraction(Decimal(str(value)))


def ratio_label(mult: Fraction) -> str:
    """Human/wire label for a qty multiplier: ``Fraction(4)`` → ``"4:1"``,
    ``Fraction(1, 4)`` → ``"1:4"``, ``Fraction(3, 2)`` → ``"3:2"``."""
    return f"{mult.numerator}:{mult.denominator}"


def classify_boundary(
    *,
    close_before: float,
    close_after: float,
    volume_before: float,
    volume_after: float,
    qty: Decimal,
) -> BoundaryVerdict:
    """Classify one before→after boundary (pure, market-agnostic).

    Returns KIND_NONE when the boundary is not a candidate discontinuity (or
    the evidence is insufficient — missing/non-positive prior close, no prior
    bar); KIND_CLEAN when the triple gate confirms a frozen split ratio;
    KIND_UNRESOLVED when a candidate cannot be explained by a clean ratio
    (fail-closed — never guess, never silently pass).
    """
    # Insufficient evidence: a usable boundary needs two positive finite closes.
    if not (_positive_finite(close_before) and _positive_finite(close_after)):
        return BoundaryVerdict(KIND_NONE)
    dec_before = Decimal(str(close_before))
    dec_after = Decimal(str(close_after))
    observed = dec_after / dec_before  # Decimal division (28-digit context)
    price_ratio = Fraction(dec_after) / Fraction(dec_before)  # exact, for gates

    # Candidate band: outside (2/3, 3/2).  ratio == 1 is inside → no event.
    if _BAND_LOW < price_ratio < _BAND_HIGH:
        return BoundaryVerdict(KIND_NONE, observed_ratio=observed)

    # Price gate: does the ratio match 1/mult for a frozen clean multiplier?
    matched: Fraction | None = None
    for mult in CLEAN_QTY_MULTIPLIERS:
        clean_price = 1 / mult
        if abs(price_ratio - clean_price) <= PRICE_RATIO_REL_TOL * clean_price:
            matched = mult
            break
    if matched is None:
        # Candidate but no clean ratio explains it → fail-closed unresolved.
        return BoundaryVerdict(KIND_UNRESOLVED, observed_ratio=observed)

    # Volume gate: same-direction multiple confirmation (price 1/4 ⇒ vol 4x).
    if not (_positive_finite(volume_before) and _positive_finite(volume_after)):
        return BoundaryVerdict(KIND_UNRESOLVED, qty_multiplier=None, observed_ratio=observed)
    volume_ratio = _fraction(volume_after) / _fraction(volume_before)
    if abs(volume_ratio - matched) > VOLUME_RATIO_REL_TOL * matched:
        return BoundaryVerdict(KIND_UNRESOLVED, observed_ratio=observed)

    # NAV gate: post-adjustment continuity vs the prior close (±0.01%, R6-1).
    qty_frac = Fraction(qty)
    prior_value = qty_frac * Fraction(dec_before)
    if prior_value > 0:
        adjusted_value = qty_frac * matched * Fraction(dec_after)
        if abs(adjusted_value - prior_value) > NAV_CONTINUITY_REL_TOL * prior_value:
            return BoundaryVerdict(KIND_UNRESOLVED, observed_ratio=observed)
    return BoundaryVerdict(KIND_CLEAN, qty_multiplier=matched, observed_ratio=observed)


def detect_symbol(
    symbol: str,
    sym_data: "SymbolData",
    matching_days: Collection[str],
    qty: Decimal,
) -> tuple[SplitEvent, ...]:
    """Pure per-symbol detector over the served frame (lookback included).

    Scans only boundaries whose AFTER-date is a simulated day (note 2); the
    BEFORE bar may be a lookback row (required when ``from_date`` is the
    ex-date).  Boundaries wholly inside the lookback are never scanned.
    """
    frame = sym_data.frame
    if frame.empty or len(frame) < 2 or not matching_days:
        return ()
    days = frozenset(matching_days)
    untradable = frozenset(sym_data.untradable_dates)
    dates = [stamp.strftime("%Y-%m-%d") for stamp in frame.index]
    closes = frame["close"]
    volumes = frame["volume"]
    events: list[SplitEvent] = []
    for i in range(1, len(frame)):
        # Note 2: only simulated-day boundaries are candidates.  R-V3 flagged
        # bars are unusable for any consumption (slot 3 rejects that day).
        if dates[i] not in days or dates[i] in untradable or dates[i - 1] in untradable:
            continue
        verdict = classify_boundary(
            close_before=float(closes.iloc[i - 1]), close_after=float(closes.iloc[i]),
            volume_before=float(volumes.iloc[i - 1]), volume_after=float(volumes.iloc[i]),
            qty=qty,
        )
        if verdict.kind == KIND_NONE:
            continue
        events.append(SplitEvent(
            symbol=symbol, date=dates[i], detected=(verdict.kind == KIND_CLEAN),
            qty_multiplier=verdict.qty_multiplier,
            observed_ratio=verdict.observed_ratio if verdict.observed_ratio is not None else _ZERO_DEC,
        ))
    return tuple(events)


def _qty_by_symbol(positions: Sequence["Position"]) -> dict[str, Decimal]:
    qty: dict[str, Decimal] = {}
    for position in positions:
        qty[position.symbol] = qty.get(position.symbol, _ZERO_DEC) + Decimal(str(position.qty))
    return qty


def build_plan(
    market_data: "MarketDataResult",
    matching_days: Collection[str],
    positions: Sequence["Position"],
) -> CorporateActionPlan:
    """Assemble the per-day plan across all served symbols (sorted, VD-10).

    ``matching_days`` are the simulated days (skip_reason is None) from the
    engine's day plan; ``positions`` is the input account_state.positions
    (the detector's NAV gate consumes the current qty per symbol).  Warnings
    are deterministic English with no timestamps (VD-7); provenance entries
    are ordered by symbol then date.
    """
    if not matching_days:
        return EMPTY_PLAN
    qty_map = _qty_by_symbol(positions)
    clean_by_day: dict[str, list[SplitEvent]] = {}
    unresolved_by_day: dict[str, list[str]] = {}
    warnings: list[str] = []
    provenance: list[dict[str, Any]] = []
    for symbol in market_data.symbols:  # served order = sorted (VD-10)
        sym_data = market_data.data.get(symbol)
        if sym_data is None:
            continue
        for event in detect_symbol(symbol, sym_data, matching_days, qty_map.get(symbol, _ZERO_DEC)):
            observed = str(event.observed_ratio)
            if event.detected and event.qty_multiplier is not None:
                label = ratio_label(event.qty_multiplier)
                clean_by_day.setdefault(event.date, []).append(event)
                warnings.append(
                    f"corporate action: {symbol} split {label} on {event.date}; position qty "
                    f"x{event.qty_multiplier}, avg_cost /{event.qty_multiplier}; nav continuous "
                    "within 0.01%")
                provenance.append(
                    {"symbol": symbol, "date": event.date, "ratio": label, "detected": True})
            else:
                unresolved_by_day.setdefault(event.date, []).append(symbol)
                warnings.append(
                    f"corporate action unresolved: {symbol} on {event.date}; close-to-close "
                    f"ratio {observed} matches no clean split ratio with volume confirmation; "
                    f"orders for {symbol} on {event.date} are rejected fail-closed "
                    "(corporate_action_unresolved)")
                provenance.append(
                    {"symbol": symbol, "date": event.date, "ratio": observed, "detected": False})
    return CorporateActionPlan(
        clean_by_day={day: tuple(events) for day, events in sorted(clean_by_day.items())},
        unresolved_by_day={
            day: tuple(sorted(set(symbols))) for day, symbols in sorted(unresolved_by_day.items())},
        warnings=tuple(warnings),
        provenance=tuple(provenance),
    )


def merge_unresolved(
    injected: Mapping[str, Collection[str]] | None,
    detected: Mapping[str, Collection[str]],
) -> dict[str, tuple[str, ...]]:
    """Union the injectable T3 seam with the detector output (never replace).

    The existing ``corporate_action_unresolved_by_day`` override keeps working
    (T3 tests rely on it); detector findings are added, so a symbol rejected
    by either source is rejected.  Deterministic: days sorted, symbols sorted.
    """
    merged: dict[str, set[str]] = {}
    for source in (injected or {}, detected):
        for day, symbols in source.items():
            merged.setdefault(day, set()).update(str(symbol) for symbol in symbols)
    return {day: tuple(sorted(symbols)) for day, symbols in sorted(merged.items())}
