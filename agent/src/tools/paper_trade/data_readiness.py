"""Target-day readiness verdicts for ``paper_trade_step`` (AM-5 / AM-6 / AM-9).

Extracted from :mod:`data` (T5): the fetch layer re-exports these names, so
existing ``data.assess_readiness`` / ``data.ReadinessVerdict`` imports keep
working.  This module is a LEAF — it imports nothing from :mod:`data` at module
scope (only the result types under ``TYPE_CHECKING``), which is what lets
:mod:`data` import it back without an import cycle.

``assess_readiness`` judges the FEDERATED MERGED frame, never a leg alone (CH
is T-1 caliber — judging on it would false-alarm ``PAPER_DATA_NOT_READY`` every
trading day).  ``ready=False`` carries the frozen in-band envelope material
(AM-5); this layer never raises for data-not-ready.

Determinism (R1-1): NO clock is read — every date is injected, so the CH UTC
vs host CST 8h skew cannot leak into verdicts.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .data import MarketDataResult

__all__ = [
    "NOT_READY_CODE",
    "ReadinessVerdict",
    "assess_readiness",
    "day_bar_availability",
]

#: Frozen in-band envelope code (schema.ERROR_CODES member) for target-day
#: all-market zero bar (AM-5/AM-9).
NOT_READY_CODE = "PAPER_DATA_NOT_READY"


@dataclass(frozen=True, slots=True)
class ReadinessVerdict:
    """Target-day readiness (AM-9).  ``ready=False`` carries the frozen in-band
    envelope material (AM-5) — this layer never raises for data-not-ready."""

    ready: bool
    code: str | None = None
    message: str | None = None


# Date normalization shared with the fetch layer (``data`` imports it back); it
# lives here so this module keeps no runtime dependency on ``data``.
def _normalize_day(value: str) -> str:
    return dt.date.fromisoformat(str(value).strip()).isoformat()


def assess_readiness(result: MarketDataResult, target_day: str) -> ReadinessVerdict:
    """Target-day readiness on the merged frame (AM-9), never on a leg alone.

    Ready when ANY served symbol carries the target-day bar (single-symbol
    absence is a suspended fact for the engine, AM-6③); all-market zero bar →
    the frozen PAPER_DATA_NOT_READY material (message follows the R1-4 example
    shape; deterministic English, no timestamps — VD-7).  An empty universe is
    vacuously ready.
    """
    day = _normalize_day(target_day)
    if not result.symbols:
        return ReadinessVerdict(ready=True)
    if result.interval == "5m":
        return _assess_five_minute_readiness(result, day)
    if not any(result.data[symbol].has_bar(day) for symbol in result.symbols):
        ends = result.provenance.bars_as_of or "empty"
        message = f"target bar {day} not available from served sources ({result.provenance.source} frame ends {ends})"
        return ReadinessVerdict(ready=False, code=NOT_READY_CODE, message=message)
    return ReadinessVerdict(ready=True)


def _assess_five_minute_readiness(result: MarketDataResult, day: str) -> ReadinessVerdict:
    # D6 fail-closed: a leg mismatch is a provider/federation fault, and an
    # all-symbol zero-bar day cannot be told apart from a market-wide outage;
    # both are PAPER_DATA_NOT_READY (retryable), never a silent halted day.
    if result.five_minute_error:
        return ReadinessVerdict(
            ready=False, code=NOT_READY_CODE, message=result.five_minute_error)
    five = result.five_minute_symbols
    if not five:
        # An explicitly empty 5m universe (pure-valuation step) issues no 5m
        # request, so its NAV comes from the daily leg and that leg must carry
        # the target day — exactly the interval="1d" contract.  A result built
        # before the field existed carries session evidence instead; fall back
        # to the whole universe only in that legacy shape.
        if not any(result.data[s].session_bars for s in result.symbols):
            if not any(result.data[s].has_bar(day) for s in result.symbols):
                ends = result.provenance.bars_as_of or "empty"
                message = (f"target bar {day} not available from served sources "
                           f"({result.provenance.source} frame ends {ends})")
                return ReadinessVerdict(ready=False, code=NOT_READY_CODE, message=message)
            return ReadinessVerdict(ready=True)
        five = result.symbols
    traded = [symbol for symbol in five if result.data[symbol].has_session_bar(day)]
    # Provider omission = the daily leg proves the symbol traded and the 5m
    # response carried NO row for it at all.  A symbol served only an auction
    # print has 5m evidence, so its empty continuous session is a halt (N3).
    provider_missing = [
        symbol for symbol in five
        if symbol not in traded
        and result.data[symbol].has_bar(day)
        and not result.data[symbol].has_five_minute_rows(day)
    ]
    if provider_missing:
        return ReadinessVerdict(
            ready=False, code=NOT_READY_CODE,
            message=(f"5m data: provider omitted the 5m leg on {day} for "
                     f"{', '.join(provider_missing)} although the daily bar exists; "
                     "stk_mins quota or permission likely; retry after the quota window"),
        )
    if not traded:
        # No order symbol carries a 5m session bar.  A universe symbol with a
        # daily bar proves the exchange traded that day, so the zero-bar order
        # symbols are genuine halts; with no bar anywhere it is an outage.
        if not any(result.data[symbol].has_bar(day) for symbol in result.symbols):
            ends = result.provenance.bars_as_of or "empty"
            return ReadinessVerdict(
                ready=False, code=NOT_READY_CODE,
                message=(f"no 5m session bar for {day} from served sources "
                         f"({result.provenance.source}; daily frame ends {ends})"),
            )
        return ReadinessVerdict(ready=True)
    mismatched = tuple(
        symbol for symbol in result.five_minute_contradiction.get(day, ()) if symbol in five)
    if mismatched:
        return ReadinessVerdict(
            ready=False, code=NOT_READY_CODE,
            message=(f"5m data is inconsistent on {day}: {', '.join(mismatched)} has a daily bar "
                     "and a 5m session bar is missing (or the reverse); refusing to read a "
                     "provider fault as a halt"),
        )
    return ReadinessVerdict(ready=True)


def day_bar_availability(result: MarketDataResult, dates: Any) -> dict[str, tuple[str, ...]]:
    # Per-day sorted tuple of symbols WITH a bar — the AM-6 matrix input
    # (dates: iterable of YYYY-MM-DD, e.g. hk_us_candidate_days output).
    availability: dict[str, tuple[str, ...]] = {}
    for raw in dates:
        day = _normalize_day(raw)
        availability[day] = tuple(s for s in result.symbols if result.data[s].has_bar(day))
    return availability
