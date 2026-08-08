"""Shared period-frame selection for SEC XBRL ``companyfacts`` rows.

``companyfacts`` interleaves several kinds of fact row that can share an ``end``
date:

* **instant** facts (balance-sheet concepts) carry no ``start`` at all;
* **true-quarter** duration frames span roughly 90 days;
* **year-to-date** duration frames span roughly 180 or 270 days;
* **full-year** duration frames span roughly 365 days.

A 10-Q reports the true quarter *and* the year-to-date frame for the same
``end``, under the same ``fy``, ``fp``, ``form`` and ``accn``. Any consumer that
identifies a period by ``end`` — with or without those four companions —
therefore silently conflates a nine-month figure with the quarter that ends on
the same day. On live AAPL revenue data 36 of 81 such keys collide.

The only field that separates them is ``start``, so the identity of a reporting
period is exactly the ``(start, end)`` span. This module is the single
implementation of that rule; ``fundamentals_loader`` and the SEC tools all route
through it rather than re-deriving the thresholds.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Inclusive day-count windows. Quarters run 89-93 days but issuers with 4-4-5
# fiscal calendars stretch further, and 52/53-week years land either side of
# 365, so both windows are deliberately generous.
QUARTER_SPAN_DAYS = (60, 120)
ANNUAL_SPAN_DAYS = (330, 380)

#: Period-type labels emitted by :func:`classify_span`.
INSTANT = "instant"
QUARTER = "quarter"
ANNUAL = "annual"
YTD = "ytd"


def span_days(row: dict[str, Any]) -> int | None:
    """Return the number of days a duration fact covers.

    Args:
        row: One SEC ``companyfacts`` unit row.

    Returns:
        The day count between ``start`` and ``end``, or ``None`` when the row is
        an instant fact (no ``start``) or either date fails to parse.
    """
    start, end = row.get("start"), row.get("end")
    if not start or not end:
        return None
    start_ts = pd.to_datetime(start, errors="coerce")
    end_ts = pd.to_datetime(end, errors="coerce")
    if pd.isna(start_ts) or pd.isna(end_ts):
        return None
    return int((end_ts - start_ts).days)


def is_quarter_span(days: int | None) -> bool:
    """Return whether ``days`` falls in the true-quarter window."""
    return days is not None and QUARTER_SPAN_DAYS[0] <= days <= QUARTER_SPAN_DAYS[1]


def is_annual_span(days: int | None) -> bool:
    """Return whether ``days`` falls in the full-year window."""
    return days is not None and ANNUAL_SPAN_DAYS[0] <= days <= ANNUAL_SPAN_DAYS[1]


def classify_span(days: int | None) -> str:
    """Label a span as instant, quarter, annual, or year-to-date.

    Args:
        days: Output of :func:`span_days`.

    Returns:
        One of :data:`INSTANT`, :data:`QUARTER`, :data:`ANNUAL`, :data:`YTD`.
        Anything that is a duration but matches neither the quarter nor the
        annual window is year-to-date or a stub period, and is labelled
        :data:`YTD` so a caller never mistakes it for a reporting period.
    """
    if days is None:
        return INSTANT
    if is_quarter_span(days):
        return QUARTER
    if is_annual_span(days):
        return ANNUAL
    return YTD


def frame_key(row: dict[str, Any]) -> tuple[Any, Any]:
    """Return the identity of the reporting period a fact row belongs to.

    ``(start, end)`` and nothing else. Including ``fy`` would split one period
    into a separate row per filing that reports it as a comparative, and
    including only ``end`` would collide a year-to-date frame with the true
    quarter ending the same day.

    Args:
        row: One SEC ``companyfacts`` unit row.

    Returns:
        The ``(start, end)`` pair; ``start`` is ``None`` for instant facts.
    """
    return (row.get("start"), row.get("end"))


def matches_cadence(row: dict[str, Any], period: str) -> bool:
    """Return whether a fact row is a reporting period at the requested cadence.

    Args:
        row: One SEC ``companyfacts`` unit row.
        period: ``"annual"`` or ``"quarter"``.

    Returns:
        ``True`` for instant facts (they are valid at any cadence and are keyed
        on ``end``), for full-year frames when ``period`` is ``"annual"``, and
        for true-quarter frames when ``period`` is ``"quarter"``. Year-to-date
        frames never match.
    """
    kind = classify_span(span_days(row))
    if kind == INSTANT:
        return True
    if period == "annual":
        return kind == ANNUAL
    return kind == QUARTER
