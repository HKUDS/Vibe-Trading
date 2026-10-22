"""Trading-day arithmetic for the incremental account (T5, AM-6 matrix).

Pure date arithmetic on injected strings plus the two calendar lookups the daily
advance needs.  No clock: "today" is always supplied by the caller.

Market strategy (mirrors ``calendar.py``):

* **cn_a** — the injected ClickHouse ``trade_calendar`` is the truth.  A date
  with no row is NOT a trading day (fail closed).
* **hk/us** — zero-calendar by design (AM-6): weekdays are candidates and the
  engine classifies a weekday holiday from bar availability.  ``is_open_day``
  therefore answers ``True`` for a weekday there; the engine's
  ``market_closed_inferred`` / ``PAPER_DATA_NOT_READY`` verdict is the real gate.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import calendar as trade_calendar
from .account import require_date

__all__ = [
    "calendar_days",
    "is_open_day",
    "latest_completed_trading_day",
    "next_day",
    "previous_day",
    "trading_days_between",
]

#: How far back ``latest_completed_trading_day`` looks.  Three weeks covers
#: every cn_a closure cluster (Spring Festival plus its surrounding weekends is
#: the longest) without turning the lookup into a calendar-history query.
CANDIDATE_LOOKBACK_DAYS = 21


def next_day(day: str) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()


def previous_day(day: str) -> str:
    return (dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat()


def calendar_days(start: str, end: str) -> tuple[str, ...]:
    """Every Gregorian day in ``[start, end]``, ascending."""
    days: list[str] = []
    day = dt.date.fromisoformat(start)
    last = dt.date.fromisoformat(end)
    while day <= last:
        days.append(day.isoformat())
        day += dt.timedelta(days=1)
    return tuple(days)


def trading_days_between(
    calendar_client: Any, market: str, start: str, end: str
) -> tuple[str, ...]:
    """Trading days of ``market`` in ``[start, end]``; ``()`` for an empty range."""
    if start > end:
        return ()
    if market == trade_calendar.CN_A_MARKET:
        return trade_calendar.trading_days_in_range(calendar_client, market, start, end)
    return trade_calendar.hk_us_candidate_days(start, end)


def is_open_day(calendar_client: Any, market: str, day: str) -> bool:
    """Whether ``day`` is a trading day, per the market's AM-6 strategy."""
    if market == trade_calendar.CN_A_MARKET:
        return trade_calendar.is_trading_day(calendar_client, market, day)
    # Zero-calendar markets: weekends are non-trading by Gregorian fact.  A
    # weekday holiday still needs bar evidence, which the engine owns; but a
    # Saturday can never be a session, so it must advance the watermark instead
    # of calling step_fn.
    return dt.date.fromisoformat(day).weekday() < 5


def latest_completed_trading_day(
    *, calendar_client: Any, market: str, today: str
) -> str | None:
    """The most recent trading day on or before ``today`` (``None`` if none found)."""
    end = require_date(today, "today")
    start = (
        dt.date.fromisoformat(end) - dt.timedelta(days=CANDIDATE_LOOKBACK_DAYS)
    ).isoformat()
    days = trading_days_between(calendar_client, market, start, end)
    return days[-1] if days else None
