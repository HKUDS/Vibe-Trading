"""Pure data models and threshold logic for strategy-discovery evidence.

This module is intentionally I/O-free so it can be imported cheaply and unit
tested without a database or the network. It defines the two frozen dataclasses
(``EvidenceRow``, ``StrategySummary``) that flow between the evidence store,
the evidence harness, and the facade, plus the small set of pure helper
functions used to classify evidence quality, compute the sizing-corrected
breakeven fee, and derive the month-granularity date coverage span.

The numeric thresholds here are the single source of truth for what counts as
``adequate`` / ``marginal`` / ``insufficient`` evidence. The facade and the
harness import these constants rather than re-deriving them, so the #969
adversarial borders (buffered "borderline" bands) stay consistent everywhere.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Regime vocabulary
# ---------------------------------------------------------------------------

#: Canonical market-regime labels. Evidence rows must carry exactly one of
#: these; ``EvidenceRow.__post_init__`` rejects anything else.
REGIMES = ("bear_market", "bull_market", "structural")

#: Evidence-stage ladder (issue #969 discussion, initial-d). Every row names
#: the stage of the pipeline that produced it; today only ``backtest`` is
#: written (the harness computes over backtest artifacts), the remaining
#: stages are reserved so holdout/shadow/live evidence can join later
#: without a schema change.
EVIDENCE_STAGES = (
    "hypothesis",
    "backtest",
    "holdout",
    "shadow",
    "live_canary",
    "retired",
)

# ---------------------------------------------------------------------------
# Evidence-quality ladder
# ---------------------------------------------------------------------------

QUALITY_ADEQUATE = "adequate"
QUALITY_MARGINAL = "marginal"
QUALITY_INSUFFICIENT = "insufficient"

#: Ordering used to compare quality floors and to sort results best-first.
QUALITY_ORDER = {
    QUALITY_ADEQUATE: 2,
    QUALITY_MARGINAL: 1,
    QUALITY_INSUFFICIENT: 0,
}

# ---------------------------------------------------------------------------
# Thresholds (single source of truth)
# ---------------------------------------------------------------------------

#: Minimum number of trades inside a regime before the evidence can rise
#: above "insufficient".
MIN_TRADES = 10

#: Minimum calendar span (in days) of the evidence window. Below this the
#: evidence is capped at "marginal" even with plenty of trades.
MIN_COVERAGE_DAYS = 730

#: Breakeven fee (in basis points) below which a strategy is considered too
#: cost-sensitive to recommend without an explicit cost feasibility check.
COST_SENSITIVE_BREAKEVEN_BPS = 5.0

#: A row that passes the hard thresholds but sits inside these buffered bands
#: is flagged "borderline" so callers cite the raw figures, not the verdict.
BORDERLINE_TRADE_BUFFER = 5
BORDERLINE_BREAKEVEN_BPS = 10.0
BORDERLINE_COVERAGE_BUFFER_DAYS = 365

# ---------------------------------------------------------------------------
# Evidence decay vocabulary and thresholds (Phase 2, #969)
# ---------------------------------------------------------------------------

#: Decay verdict vocabulary. Computed AT READ TIME from the evidence itself
#: (window recency) — never persisted, never derived from model memory.
DECAY_FRESH = "fresh"
DECAY_AGING = "aging"
DECAY_STALE = "stale"

#: Evidence-window age (days since the latest ``date_ranges`` window ended)
#: at or above which a row is flagged ``aging``. Justified against the
#: documented quarterly re-backtest cadence: a window end more than ~90 days
#: old means the strategy has missed at least one scheduled re-verification
#: cycle, so the row carries an ``aged-evidence:`` warning — but it is NOT
#: excluded, because one missed cycle is recoverable.
DECAY_AGING_EVIDENCE_AGE_DAYS = 90

#: Evidence-window age (days) at or above which a row is ``stale`` and is
#: excluded from default recommendations. A window end more than ~180 days
#: old means at least two consecutive quarterly re-backtest cycles were
#: missed; the evidence can no longer vouch for the current market, so the
#: row is refused by default (inspectable via ``include_stale``).
#: Boundary semantics: ``age >= DECAY_STALE_EVIDENCE_AGE_DAYS`` ⇒ stale,
#: elif ``age >= DECAY_AGING_EVIDENCE_AGE_DAYS`` ⇒ aging, else fresh — the
#: exact threshold belongs to the STRICTER side (fail-closed, sergio12S).
DECAY_STALE_EVIDENCE_AGE_DAYS = 180

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceRow:
    """A single (strategy, regime) evidence record.

    All return-like fields are decimal fractions (``0.083`` == +8.3%) so the
    facade can render them without guessing at units. Optional fields are
    ``None`` when the underlying artifact simply did not record them — we
    never invent a placeholder number.
    """

    strategy_id: str
    regime: str
    trades_in_regime: int
    #: Average deployed equity fraction in (0, 1]; ``None`` when unknown.
    position_size: float | None = None
    return_in_regime: float | None = None
    benchmark_in_regime: float | None = None
    excess_in_regime: float | None = None
    sharpe_in_regime: float | None = None
    max_drawdown_in_regime: float | None = None
    #: Each entry is "YYYY-MM to YYYY-MM". Kept as a tuple so the dataclass
    #: stays hashable / frozen-friendly.
    date_ranges: tuple[str, ...] = ()
    breakeven_fee_bps: float | None = None
    cost_sensitive: bool = False
    evidence_quality: str = QUALITY_INSUFFICIENT
    warnings: tuple[str, ...] = ()
    #: ISO date string ("YYYY-MM-DD") of the last harness verification.
    last_verified: str = ""
    #: Pipeline stage that produced this row; one of ``EVIDENCE_STAGES``.
    evidence_stage: str = "backtest"
    #: Reproducible artifact reference: the backtest run directory whose
    #: ``artifacts/`` this row was computed from.
    provenance: str = ""
    #: JSON string naming the regime-labeling parameters (window, bear/bull
    #: thresholds, Sharpe annualization) used when this row was computed.
    regime_definition: str = ""

    def __post_init__(self) -> None:
        if self.regime not in REGIMES:
            raise ValueError(
                f"invalid regime {self.regime!r}; expected one of {REGIMES}"
            )
        if self.evidence_stage not in EVIDENCE_STAGES:
            raise ValueError(
                f"invalid evidence_stage {self.evidence_stage!r}; "
                f"expected one of {EVIDENCE_STAGES}"
            )


@dataclass(frozen=True)
class StrategySummary:
    """Catalog entry surfaced by :meth:`StrategyDiscoveryFacade.list_strategies`.

    ``source`` is ``"alpha_zoo"`` or ``"sdm"``. ``status`` mirrors the SDM
    lifecycle state and is ``None`` for alpha-zoo entries, which have no
    lifecycle.
    """

    strategy_id: str
    name: str
    source: str
    description: str | None = None
    status: str | None = None
    universe: str | None = None
    has_evidence: bool = False
    regimes_with_evidence: tuple[str, ...] = field(default=())


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _parse_month_first(token: str) -> date | None:
    """Parse a ``YYYY-MM`` token into the first day of that month."""
    token = token.strip()
    match = re.fullmatch(r"(\d{4})-(\d{1,2})", token)
    if match is None:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return date(year, month, 1)


def _month_last_day_anchor(start_of_month: date) -> date:
    """Return the last calendar day of the month containing ``start_of_month``."""
    if start_of_month.month == 12:
        return date(start_of_month.year, 12, 31)
    return date(start_of_month.year, start_of_month.month + 1, 1) - timedelta(days=1)


def coverage_days_from_ranges(date_ranges) -> int:
    """Span from the earliest range start to the latest range end, in days.

    Each entry is parsed as ``"YYYY-MM to YYYY-MM"``; the span runs from the
    first day of the earliest start month to the last day of the latest end
    month. Malformed entries contribute nothing. Returns ``0`` when no entry
    parses cleanly (an honest zero rather than a fabricated span).
    """
    min_start: date | None = None
    max_end: date | None = None

    for entry in date_ranges:
        if not isinstance(entry, str):
            continue
        pieces = [p for p in re.split(r"\s+to\s+", entry.strip(), flags=re.IGNORECASE)]
        if len(pieces) != 2:
            continue
        start = _parse_month_first(pieces[0])
        end_start = _parse_month_first(pieces[1])
        if start is None or end_start is None:
            continue
        end = _month_last_day_anchor(end_start)
        if min_start is None or start < min_start:
            min_start = start
        if max_end is None or end > max_end:
            max_end = end

    if min_start is None or max_end is None:
        return 0
    return max(0, (max_end - min_start).days)


def classify_quality(trades_in_regime: int, coverage_days: int) -> str:
    """Map (trade count, coverage span) onto the quality ladder."""
    if trades_in_regime < MIN_TRADES:
        return QUALITY_INSUFFICIENT
    if coverage_days < MIN_COVERAGE_DAYS:
        return QUALITY_MARGINAL
    return QUALITY_ADEQUATE


def evidence_window_end(date_ranges) -> date | None:
    """Last calendar day of the latest evidence window, or ``None``.

    Each entry is parsed as ``"YYYY-MM to YYYY-MM"``; the window end is the
    last day of the latest end month (month-granular ranges are end-anchored
    to month-end, see :func:`_month_last_day_anchor`). Malformed entries
    contribute nothing; ``None`` when nothing parses cleanly.
    """
    max_end: date | None = None

    for entry in date_ranges:
        if not isinstance(entry, str):
            continue
        pieces = [p for p in re.split(r"\s+to\s+", entry.strip(), flags=re.IGNORECASE)]
        if len(pieces) != 2:
            continue
        end_start = _parse_month_first(pieces[1])
        if end_start is None:
            continue
        end = _month_last_day_anchor(end_start)
        if max_end is None or end > max_end:
            max_end = end

    return max_end


def evidence_age_days(date_ranges, today: date) -> int | None:
    """Age in days of the latest evidence window relative to ``today``.

    ``today − evidence_window_end``, clamped to ``>= 0``: month-granular
    ranges are end-anchored to month-end, so a window ending in the current
    month can land in the future relative to ``today`` — a negative age is
    reported as 0 (freshest possible), never as a negative number. Returns
    ``None`` when no window end parses (callers fail closed on that).
    """
    window_end = evidence_window_end(date_ranges)
    if window_end is None:
        return None
    return max(0, (today - window_end).days)


def staleness_days(last_verified: str, today: date) -> int | None:
    """Days since the row was last verified; ``None`` for malformed input.

    Reported on every returned row but NEVER used for gating (plan D1):
    ``staleness_days`` would let a scheduled refresh of unchanged artifacts
    keep every row "fresh" forever — decay gating is driven by
    :func:`evidence_age_days` instead.
    """
    if not isinstance(last_verified, str):
        return None
    text = last_verified.strip()
    if not text:
        return None
    try:
        verified = date.fromisoformat(text[:10])
    except ValueError:
        return None
    return max(0, (today - verified).days)


def classify_decay(
    date_ranges,
    today: date,
    aging_days: int = DECAY_AGING_EVIDENCE_AGE_DAYS,
    stale_days: int = DECAY_STALE_EVIDENCE_AGE_DAYS,
) -> str:
    """Decay verdict from the evidence window recency (pure, read-time).

    Boundary semantics: ``age >= stale_days`` ⇒ ``stale``, elif
    ``age >= aging_days`` ⇒ ``aging``, else ``fresh`` — an exact threshold
    belongs to the stricter side. Unparseable/empty ``date_ranges`` classify
    as ``stale`` fail-closed: evidence whose window cannot be dated cannot
    vouch for anything (sergio12S discipline, #969).
    """
    age = evidence_age_days(date_ranges, today)
    if age is None:
        return DECAY_STALE
    if age >= stale_days:
        return DECAY_STALE
    if age >= aging_days:
        return DECAY_AGING
    return DECAY_FRESH


def decay_warning(decay_status: str, evidence_age_days: int | None) -> str | None:
    """Stable decay warning for a row, or ``None`` for fresh rows.

    Prefixes are fixed tokens (``stale-evidence:``, ``aged-evidence:``) with
    the day count in the body so downstream tools can match them without
    parsing prose. A stale verdict with an unknown age (unparseable window)
    still warns — with the unparseable reason instead of a day count.
    """
    if decay_status == DECAY_STALE:
        if evidence_age_days is None:
            return (
                "stale-evidence: evidence window end is missing or "
                "unparseable, treated as stale fail-closed — re-backtest "
                "over a recent window and refresh before relying on this row"
            )
        return (
            f"stale-evidence: evidence window ended {evidence_age_days} days "
            f"ago (>= {DECAY_STALE_EVIDENCE_AGE_DAYS}-day staleness "
            "threshold) — excluded from default recommendations; re-backtest "
            "over a recent window and refresh to reinstate"
        )
    if decay_status == DECAY_AGING:
        return (
            f"aged-evidence: evidence window ended {evidence_age_days} days "
            f"ago (>= {DECAY_AGING_EVIDENCE_AGE_DAYS}-day aging threshold) — "
            "still queryable, but verify with a fresh backtest before "
            "relying on this row"
        )
    return None


def breakeven_fee_bps(
    gross_return: float,
    trades: int,
    position_size: float | None = None,
) -> float | None:
    """Sizing-corrected breakeven transaction fee in basis points.

    Identity (per sergio12S, #969)::

        breakeven_bps = ln(1 + gross_return) / (2 * trades * position_size) * 10_000

    ``position_size`` defaults to ``1.0`` (full capital deployed) when
    ``None``. Returns ``None`` whenever the inputs are not usable (zero /
    negative trades, a return at or below -100%, a non-positive position
    size, or any non-finite value) rather than producing a meaningless or
    infinite number.
    """
    s = 1.0 if position_size is None else position_size
    try:
        gross = float(gross_return)
        n_trades = float(trades)
        size = float(s)
    except (TypeError, ValueError):
        return None

    if not (math.isfinite(gross) and math.isfinite(n_trades) and math.isfinite(size)):
        return None
    if n_trades <= 0 or gross <= -1.0 or size <= 0:
        return None

    return math.log(1.0 + gross) / (2.0 * n_trades * size) * 10_000.0


def build_warnings(
    trades_in_regime: int,
    coverage_days: int,
    breakeven: float | None,
    quality: str,
    cost_sensitive: bool,
) -> tuple[str, ...]:
    """Stable, machine-readable warning strings for an evidence row.

    Prefixes are fixed tokens (``insufficient-trades:``, ``short-coverage:``,
    ``cost-sensitive:``) so downstream tools can match them without parsing
    prose. Only conditions that actually hold emit a warning.
    """
    warnings: list[str] = []

    if trades_in_regime < MIN_TRADES:
        warnings.append(
            f"insufficient-trades: {trades_in_regime} < {MIN_TRADES} trades in regime"
        )

    if coverage_days < MIN_COVERAGE_DAYS:
        warnings.append(
            f"short-coverage: {coverage_days} days < {MIN_COVERAGE_DAYS} day window"
        )

    if cost_sensitive:
        breakeven_text = (
            f"{breakeven:.2f} bps"
            if isinstance(breakeven, float) and math.isfinite(breakeven)
            else "unknown"
        )
        warnings.append(
            f"cost-sensitive: breakeven {breakeven_text} "
            f"below {COST_SENSITIVE_BREAKEVEN_BPS:.1f} bps threshold"
        )

    return tuple(warnings)
