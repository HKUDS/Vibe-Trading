"""Read-only parsing of backtest run artifacts for the evidence harness.

Pure CSV I/O over ``run_dir/artifacts`` — no network, no invention. The
harness reads only what a reproducible run actually recorded.

Real engine schema (``backtest/engines/base.py::_write_artifacts``, the
writer every reproducible run goes through):

* ``trades.csv`` — columns ``timestamp, code, side, price, qty, reason,
  pnl, holding_days, return_pct`` with TWO rows per round trip: an entry
  row (``reason="signal"``, ``pnl=0.0``, ``holding_days=0``) followed by
  the exit row carrying the realized ``pnl``.
* ``equity.csv`` — date column ``timestamp`` (the engine's index name)
  plus ``ret, equity, drawdown, benchmark_equity, active_ret``.

Entry/exit convention. The engine writes no dedicated marker column, and
``reason`` is not one either — exits can also carry ``reason="signal"``
(the base engine closes positions on signal). This reader therefore
mirrors the repo's own artifact-reload convention in
``backtest/validation.py``: a row is a closed-trade (exit) row iff its
``pnl`` parses to a nonzero finite value, while ``pnl == 0.0`` rows are
entry rows. Files with no zero-pnl rows at all are treated as legacy
one-row-per-trade artifacts where every dated row is a meaningful closed
trade. Documented limitation (shared with ``validation.py``): an
exact-break-even exit (``pnl == 0.0``) is indistinguishable from an entry
row and is not counted as a round trip.

Legacy artifacts keep parsing through column aliases (``date`` for
``timestamp``, ``benchmark`` for ``benchmark_equity``). Unusable files —
missing date/equity columns, decode errors, OS errors, malformed CSV —
return ``None`` with a logged warning instead of raising; malformed rows
are skipped rather than guessed at.
"""

from __future__ import annotations

import csv
import json
import logging
import math
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: Accepted names for the trade-date column in ``trades.csv``. The engine
#: names it ``timestamp``; the remaining names are legacy aliases kept for
#: older artifacts. Real engine name first, legacy after.
TRADE_DATE_ALIASES = ("timestamp", "date", "trade_date", "exit_date")

#: Accepted names for the date column in ``equity.csv``. The engine writes
#: its date index as ``timestamp``; ``date`` is the legacy alias.
EQUITY_DATE_ALIASES = ("timestamp", "date")

#: Accepted names for the strategy equity column in ``equity.csv``.
EQUITY_COLUMN_ALIASES = ("equity", "nav", "value")

#: Accepted names for the benchmark column in ``equity.csv``. The engine
#: writes ``benchmark_equity``; ``benchmark`` is the legacy alias.
_BENCHMARK_ALIASES = ("benchmark_equity", "benchmark")
_EXPOSURE_ALIASES = ("exposure",)

#: Engine marker columns in ``trades.csv`` used for entry/exit detection
#: and per-code position pairing.
_PNL_ALIASES = ("pnl",)
_CODE_ALIASES = ("code",)

#: Errors that mean "artifact unreadable" rather than "bug": non-UTF-8
#: bytes, missing files/permissions, and malformed CSV (NUL bytes, broken
#: quoting, oversized fields). Readers degrade to ``None`` on all of these.
_UNREADABLE_ERRORS = (OSError, UnicodeDecodeError, csv.Error)


def parse_iso_date(token: object) -> date | None:
    """Best-effort ISO date parse; ``None`` when the token is unusable."""
    text = str(token or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y%m%d").date()
    except ValueError:
        return None


def parse_finite_float(token: object) -> float | None:
    """Parse a float; ``None`` for missing/malformed/non-finite tokens."""
    try:
        value = float(str(token).strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _find_column(fieldnames: Sequence[str], aliases: Sequence[str]) -> str | None:
    """Match a header name against aliases, case-insensitively."""
    normalized = {name.strip().lower(): name for name in fieldnames if name}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return None


def _max_concurrent_positions(intervals: Sequence[tuple[date, date]]) -> int:
    """Peak number of overlapping ``(entry, exit)`` holding intervals.

    Entries are processed before exits on the same date, so a same-day
    round trip still registers as one open position. That choice is
    deliberate: the feed into the multi-position breakeven caveat should
    over-flag rather than under-flag.
    """
    if not intervals:
        return 0
    events: list[tuple[date, int]] = []
    for entry_date, exit_date in intervals:
        start, end = sorted((entry_date, exit_date))
        events.append((start, 1))
        events.append((end, -1))
    # Same-date ordering: +1 (entry) before -1 (exit).
    events.sort(key=lambda event: (event[0], -event[1]))
    current = peak = 0
    for _, delta in events:
        current += delta
        if current > peak:
            peak = current
    return peak


def read_trade_activity(path: Path) -> tuple[list[date], int | None] | None:
    """Round-trip exit dates and peak concurrency from ``trades.csv``.

    Returns ``(exit_dates, max_concurrent)``:

    * ``exit_dates`` — one date per closed round trip, sorted. Engine
      artifacts hold two rows per round trip (entry row ``pnl=0.0`` plus
      exit row with realized pnl); only exit rows count, so a round trip
      is counted once, never twice. Legacy one-row-per-trade artifacts
      (no zero-pnl marker rows) count every dated row.
    * ``max_concurrent`` — peak simultaneously open positions derived
      from the entry/exit pairs (FIFO per code, matching the engine's
      one-position-per-symbol book), or ``None`` when the file lacks the
      zero-pnl entry marker and concurrency is undetectable.

    Returns ``None`` when the file is unusable: no date column, decode /
    OS / CSV errors, or no usable content. Rows with unparseable dates
    are skipped, never fatal. See the module docstring for the entry/exit
    marker convention.
    """
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            date_column = _find_column(fieldnames, TRADE_DATE_ALIASES)
            if date_column is None:
                logger.warning(
                    "trades.csv at %s has no date column (expected one of %s)",
                    path,
                    ", ".join(TRADE_DATE_ALIASES),
                )
                return None
            pnl_column = _find_column(fieldnames, _PNL_ALIASES)
            code_column = _find_column(fieldnames, _CODE_ALIASES)

            rows: list[tuple[date, str, float | None]] = []
            for record in reader:
                trade_date = parse_iso_date(record.get(date_column))
                if trade_date is None:
                    continue  # reject unparseable dates row-by-row
                pnl = (
                    parse_finite_float(record.get(pnl_column))
                    if pnl_column is not None
                    else None
                )
                code = (
                    str(record.get(code_column) or "").strip()
                    if code_column is not None
                    else ""
                )
                rows.append((trade_date, code, pnl))
    except _UNREADABLE_ERRORS as exc:
        logger.warning(
            "trades.csv at %s is unreadable (%s); treated as unusable", path, exc
        )
        return None

    if not rows:
        return [], None

    # The engine writes entry rows with pnl=0.0 and exit rows with realized
    # pnl (backtest/engines/base.py::_write_artifacts); backtest/validation.py
    # reloads the same artifacts with `pnl != 0` as the exit-row filter. When
    # no marker row exists, every dated row is a closed trade (legacy
    # one-row-per-trade artifacts) and concurrency is undetectable.
    has_entry_marker = any(pnl is not None and pnl == 0.0 for _, _, pnl in rows)
    if not has_entry_marker:
        return sorted(trade_date for trade_date, _, _ in rows), None

    exit_dates: list[date] = []
    open_entries: dict[str, list[date]] = {}
    intervals: list[tuple[date, date]] = []
    for trade_date, code, pnl in rows:
        if pnl is None:
            continue  # unclassifiable without a usable pnl marker
        if pnl != 0.0:
            # Exit row: one closed round trip.
            exit_dates.append(trade_date)
            pending = open_entries.get(code)
            if pending:
                intervals.append((pending.pop(0), trade_date))
        else:
            # Entry row (engine marker pnl == 0.0).
            open_entries.setdefault(code, []).append(trade_date)
    exit_dates.sort()
    return exit_dates, _max_concurrent_positions(intervals)


def read_trade_dates(path: Path) -> list[date] | None:
    """Closed-trade dates from ``trades.csv``; ``None`` when unusable.

    One date per round trip: engine artifacts carry entry+exit row pairs
    and only exit rows count. Thin wrapper around
    :func:`read_trade_activity`, which documents the marker convention
    and the legacy one-row-per-trade behavior.
    """
    activity = read_trade_activity(path)
    if activity is None:
        return None
    exit_dates, _ = activity
    return exit_dates


def read_equity_series(
    path: Path,
) -> tuple[list[date], list[float], list[float | None], list[float]] | None:
    """(dates, equity, benchmark-or-None-per-bar, exposures) from ``equity.csv``.

    Column aliases: the date column is ``timestamp`` in engine artifacts
    (legacy ``date`` still parses); the benchmark column is
    ``benchmark_equity`` in engine artifacts (legacy ``benchmark`` still
    parses). Rows without a parseable date and finite positive equity
    value are skipped. Returns ``None`` when the file lacks a usable
    date/equity column pair, contains no usable rows, or is unreadable
    (decode / OS / CSV errors degrade instead of raising).
    """
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            date_column = _find_column(fieldnames, EQUITY_DATE_ALIASES)
            equity_column = _find_column(fieldnames, EQUITY_COLUMN_ALIASES)
            if date_column is None or equity_column is None:
                logger.warning(
                    "equity.csv at %s lacks a date/equity column pair "
                    "(date aliases: %s; equity aliases: %s)",
                    path,
                    ", ".join(EQUITY_DATE_ALIASES),
                    ", ".join(EQUITY_COLUMN_ALIASES),
                )
                return None
            benchmark_column = _find_column(fieldnames, _BENCHMARK_ALIASES)
            exposure_column = _find_column(fieldnames, _EXPOSURE_ALIASES)

            records: dict[date, tuple[float, float | None, float | None]] = {}
            for record in reader:
                bar_date = parse_iso_date(record.get(date_column))
                equity = parse_finite_float(record.get(equity_column))
                if bar_date is None or equity is None or equity <= 0:
                    continue
                benchmark = (
                    parse_finite_float(record.get(benchmark_column))
                    if benchmark_column is not None
                    else None
                )
                exposure = (
                    parse_finite_float(record.get(exposure_column))
                    if exposure_column is not None
                    else None
                )
                if bar_date in records:  # duplicate dates: keep the first bar
                    continue
                records[bar_date] = (equity, benchmark, exposure)
    except _UNREADABLE_ERRORS as exc:
        logger.warning(
            "equity.csv at %s is unreadable (%s); treated as unusable", path, exc
        )
        return None

    if not records:
        return None
    ordered = sorted(records.items())
    dates = [bar_date for bar_date, _ in ordered]
    equities = [values[0] for _, values in ordered]
    benchmarks = [values[1] for _, values in ordered]
    exposures = [
        values[2] for _, values in ordered if values[2] is not None and values[2] > 0
    ]
    return dates, equities, benchmarks, exposures


# ---------------------------------------------------------------------------
# Hard-gate readers (Phase 2, #969): the backtest-diagnose hookup. Each
# reader degrades to None on unusable input so the gate fails CLOSED — an
# unverifiable run is never admitted as evidence.
# ---------------------------------------------------------------------------


def read_run_status(run_dir: str | Path) -> str | None:
    """Run status from ``state.json``; ``None`` when missing or unreadable.

    Runs carry no exit code in ``run_card.json``; the runtime writes
    ``state.json`` (``{"status": "success"|"failed"|"cancelled", ...}``).
    A missing state.json yields ``None`` — the ingestion gate treats that as
    a failure, fail-closed.
    """
    path = Path(run_dir) / "state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if not isinstance(status, str) or not status.strip():
        return None
    return status.strip()


def read_metrics_trade_count(run_dir: str | Path) -> int | None:
    """``trade_count`` from the ``artifacts/metrics.csv`` header row.

    The engine writes metrics.csv as one header row of metric names plus one
    value row. Returns ``None`` when the file is missing, has no value row,
    lacks a ``trade_count`` column, or the value is not a finite number —
    the ingestion gate treats all of these as zero trades, fail-closed.
    """
    path = Path(run_dir) / "artifacts" / "metrics.csv"
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header is None:
                return None
            normalized = [name.strip().lower() for name in header]
            if "trade_count" not in normalized:
                return None
            column = normalized.index("trade_count")
            value_row = next(reader, None)
            if value_row is None or column >= len(value_row):
                return None
            value = parse_finite_float(value_row[column])
            if value is None:
                return None
            return int(value)
    except _UNREADABLE_ERRORS as exc:
        logger.warning(
            "metrics.csv at %s is unreadable (%s); treated as unusable", path, exc
        )
        return None


def equity_has_non_finite(run_dir: str | Path) -> bool | None:
    """Scan ``artifacts/equity.csv`` equity column for NaN/Inf values.

    Returns ``True`` when any data row's equity cell is missing, malformed,
    or non-finite; ``False`` when every row carries a finite equity value.
    Returns ``None`` when the verdict itself is unverifiable — file missing
    or unreadable, no equity column, or no data rows — which the ingestion
    gate treats as ``hard-gate:equity-empty`` (fail-closed).

    Unlike :func:`read_equity_series`, which skips unusable rows, this
    reader refuses to look past them: a NaN mid-curve means the equity
    series is structurally broken and no partial-curve evidence may be
    computed from it (Phase 1 silent-skip latent, #969).
    """
    path = Path(run_dir) / "artifacts" / "equity.csv"
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            equity_column = _find_column(fieldnames, EQUITY_COLUMN_ALIASES)
            if equity_column is None:
                return None
            saw_row = False
            for record in reader:
                saw_row = True
                if parse_finite_float(record.get(equity_column)) is None:
                    return True
            if not saw_row:
                return None
            return False
    except _UNREADABLE_ERRORS as exc:
        logger.warning(
            "equity.csv at %s is unreadable (%s); treated as unusable", path, exc
        )
        return None
