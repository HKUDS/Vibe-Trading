"""Read-only parsing of backtest run artifacts for the evidence harness.

Pure CSV I/O over ``run_dir/artifacts`` — no network, no invention. The
harness reads only what a reproducible run actually recorded:

* ``trades.csv`` — one row per trade; needs a date column (aliases:
  ``date``, ``trade_date``, ``exit_date``).
* ``equity.csv`` — daily series with columns ``date``, ``equity`` (aliases
  ``nav``/``value``), optional ``benchmark`` and optional ``exposure``.

Unusable files return ``None`` with a logged warning; malformed rows are
skipped rather than guessed at.
"""

from __future__ import annotations

import csv
import logging
import math
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: Accepted names for the trade-date column in ``trades.csv``.
TRADE_DATE_ALIASES = ("date", "trade_date", "exit_date")

#: Accepted names for the strategy equity column in ``equity.csv``.
EQUITY_COLUMN_ALIASES = ("equity", "nav", "value")

_BENCHMARK_COLUMN = "benchmark"
_EXPOSURE_COLUMN = "exposure"


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


def read_trade_dates(path: Path) -> list[date] | None:
    """Trade dates from ``trades.csv``; ``None`` when the file is unusable."""
    dates: list[date] = []
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
        for record in reader:
            parsed = parse_iso_date(record.get(date_column))
            if parsed is not None:
                dates.append(parsed)
    dates.sort()
    return dates


def read_equity_series(
    path: Path,
) -> tuple[list[date], list[float], list[float | None], list[float]] | None:
    """(dates, equity, benchmark-or-None-per-bar, exposures) from ``equity.csv``.

    Rows without a parseable date and finite positive equity value are
    skipped. Returns ``None`` when the file lacks a usable date/equity
    column pair or contains no usable rows.
    """
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        date_column = _find_column(fieldnames, ("date",))
        equity_column = _find_column(fieldnames, EQUITY_COLUMN_ALIASES)
        if date_column is None or equity_column is None:
            logger.warning(
                "equity.csv at %s lacks a date/equity column pair (equity aliases: %s)",
                path,
                ", ".join(EQUITY_COLUMN_ALIASES),
            )
            return None
        benchmark_column = _find_column(fieldnames, (_BENCHMARK_COLUMN,))
        exposure_column = _find_column(fieldnames, (_EXPOSURE_COLUMN,))

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
