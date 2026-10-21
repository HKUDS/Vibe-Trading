"""Trading-calendar seam for ``paper_trade_step`` (pt-v1.1 R3 / AM-6, VD-5).

Market strategy matrix (AM-6):

* **cn_a** — ClickHouse ``ashare.trade_calendar`` is the truth
  (exchange / cal_date / is_open / pretrade_date).  The client is
  INJECTABLE: this module never constructs a connector, never touches the
  network, and is offline-testable with a fake client.
  ``ClickHouseConnector.get_trade_calendar`` (agent/src/clickhouse_connector.py:501)
  satisfies :class:`TradeCalendarClient` structurally — no wrapper needed.
* **hk / us** — APPROVED AM-6 zero-calendar fail-closed strategy (G1 open,
  2026-10-19): the engine holds NO exchange calendar for these markets and
  introduces no new dependency (``exchange_calendars``-class packages stay an
  RM-side escalation path).  Day verdicts are inferred from bar availability
  via :func:`classify_zero_calendar_day` — the three-state matrix:
  target-day all-market zero bar → ``PAPER_DATA_NOT_READY`` (retryable
  envelope); mid-range all-market zero bar → skipped reason
  ``market_closed_inferred`` + mandatory warning (never silently a
  ``non_trading_day``); single-symbol zero bar → ``suspended`` rejections +
  carry-forward valuation.  The calendar-lookup functions below stay cn_a-only
  and raise ``NotImplementedError`` for hk/us by design.  Day enumeration for
  hk/us is :func:`hk_us_candidate_days` (weekdays; weekends are non-trading by
  Gregorian fact, holidays surface as zero-bar weekdays).

Determinism: no clock, no environment, no network reads here; the same
client rows and bar-availability facts always produce the same verdicts.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import pandas as pd

__all__ = [
    "CN_A_MARKET",
    "HK_MARKET",
    "US_MARKET",
    "VERDICT_MARKET_CLOSED_INFERRED",
    "VERDICT_NOT_READY",
    "VERDICT_TRADING_DAY",
    "TradeCalendarClient",
    "ZeroCalendarDayVerdict",
    "classify_zero_calendar_day",
    "hk_us_candidate_days",
    "is_trading_day",
    "trading_days_in_range",
]

CN_A_MARKET = "cn_a"
HK_MARKET = "hk"
US_MARKET = "us"

_CALENDAR_MARKETS = (CN_A_MARKET, HK_MARKET, US_MARKET)

# AM-6 (APPROVED, G1 open 2026-10-19): hk/us are ZERO-CALENDAR markets —
# fail-closed day classification from bar availability
# (:func:`classify_zero_calendar_day`).  No exchange-calendar dependency is
# ever introduced here (REQUIREMENTS §9 red line); the escalation path
# (exchange_calendars-class) is registered RM-side.
_ZERO_CALENDAR_MARKETS = (HK_MARKET, US_MARKET)

_HK_US_NOT_IMPLEMENTED = (
    "paper_trade calendar: market {market!r} has no in-engine calendar by design "
    "(AM-6 zero-calendar fail-closed, approved): day verdicts come from bar "
    "availability via classify_zero_calendar_day — target-day all-market zero bar "
    "=> PAPER_DATA_NOT_READY, mid-range all-market zero bar => "
    "market_closed_inferred + warning, single-symbol zero bar => suspended"
)

#: AM-6 verdict kinds (frozen three-state matrix).  ``market_closed_inferred``
#: is a member of the closed ``schema.SKIPPED_DAY_REASONS`` vocabulary (pinned
#: by test); ``not_ready`` maps to the frozen ``PAPER_DATA_NOT_READY`` envelope
#: code at the tool layer (AM-5).
VERDICT_TRADING_DAY = "trading_day"
VERDICT_NOT_READY = "not_ready"
VERDICT_MARKET_CLOSED_INFERRED = "market_closed_inferred"

_MARKET_CLOSED_WARNING = (
    "no bars for any symbol on {date}: hk/us have no in-engine calendar "
    "(AM-6 zero-calendar fail-closed), so the day is inferred closed from bar "
    "availability and must be cross-checked against the RM static holiday file"
)


@dataclass(frozen=True, slots=True)
class ZeroCalendarDayVerdict:
    """One AM-6 matrix verdict for a hk/us candidate day.

    ``suspended_symbols`` is only populated on ``trading_day`` verdicts:
    symbols with zero bar that day (the engine rejects their orders with
    reason_code ``suspended`` and values their positions carry-forward).
    ``warning`` is mandatory on ``market_closed_inferred`` (never silent).
    """

    date: str
    kind: str
    suspended_symbols: tuple[str, ...] = ()
    warning: str | None = None


class TradeCalendarClient(Protocol):
    """Structural interface for calendar lookups.

    ``ClickHouseConnector`` satisfies it as-is: ``get_trade_calendar``
    returns a DataFrame with columns ``exchange, cal_date, is_open,
    pretrade_date`` for the inclusive ``YYYY-MM-DD`` range.  Tests inject
    a fake returning recorded rows — never the network.
    """

    def get_trade_calendar(self, start_date: str, end_date: str) -> "pd.DataFrame":
        ...


def _normalize_date(value: str) -> str:
    """Normalize a calendar date to ``YYYY-MM-DD``.

    The connector documents ``YYYY-MM-DD`` parameters, but the stored
    ``cal_date`` spelling is unverified while ClickHouse is unreachable
    (Step 0 DD-5 live column recheck pending); tushare-lineage exports
    commonly use ``YYYYMMDD``.  Both spellings normalize; anything else
    fails closed with a deterministic message.
    """
    text = str(value).strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    raise ValueError(f"unrecognized calendar date format: {value!r}")


def _cn_a_open_map(client: TradeCalendarClient, start_date: str, end_date: str) -> dict[str, bool]:
    """Query the CH calendar once and reduce rows to {date: is_open}.

    The table carries one row per exchange per date; SSE and SZSE share the
    cn_a holiday calendar, so a date aggregates as open when ANY row says
    open — robust to single-exchange exports and deterministic either way.
    A date with no row at all is NOT a confirmed trading day (the table is
    the truth source and expected complete; fail closed).
    """
    frame = client.get_trade_calendar(start_date, end_date)
    open_map: dict[str, bool] = {}
    for record in frame.to_dict("records"):
        date = _normalize_date(record["cal_date"])
        is_open = int(record["is_open"]) == 1
        open_map[date] = open_map.get(date, False) or is_open
    return open_map


def _ensure_calendar_market(market: str) -> None:
    if market not in _CALENDAR_MARKETS:
        raise ValueError(f"unknown market for calendar lookup: {market!r}")
    if market in _ZERO_CALENDAR_MARKETS:
        raise NotImplementedError(_HK_US_NOT_IMPLEMENTED.format(market=market))


def is_trading_day(client: TradeCalendarClient, market: str, date: str) -> bool:
    """Whether ``date`` (YYYY-MM-DD) is a trading day of ``market``.

    cn_a: CH ``trade_calendar`` truth.  hk/us: raises NotImplementedError
    (AM-6 zero-calendar — use :func:`classify_zero_calendar_day`).  Unknown
    market: ValueError.
    """
    _ensure_calendar_market(market)
    day = _normalize_date(date)
    return _cn_a_open_map(client, day, day).get(day, False)


def trading_days_in_range(
    client: TradeCalendarClient, market: str, from_date: str, to_date: str
) -> tuple[str, ...]:
    """Open trading days within the inclusive range, ascending (R3 driver).

    The engine's day loop (Step 3) consumes this to emit ``skipped_days``
    rows with reason ``non_trading_day`` for the closed dates in between.
    """
    _ensure_calendar_market(market)
    start = _normalize_date(from_date)
    end = _normalize_date(to_date)
    open_map = _cn_a_open_map(client, start, end)
    # Clamp to the requested range: the real connector filters in SQL, but
    # the contract this function guarantees is "open days within [start, end]"
    # regardless of what the client hands back.
    return tuple(sorted(date for date, is_open in open_map.items() if is_open and start <= date <= end))


def hk_us_candidate_days(from_date: str, to_date: str) -> tuple[str, ...]:
    """Weekdays (Mon-Fri) within the inclusive range, ascending.

    Zero-calendar day enumeration for hk/us: weekends are non-trading by
    Gregorian fact (no exchange-calendar dependency); holiday closures surface
    as zero-bar weekdays and are classified by
    :func:`classify_zero_calendar_day`.  Pure date arithmetic on injected
    strings — deterministic, no clock.
    """
    start = dt.date.fromisoformat(_normalize_date(from_date))
    end = dt.date.fromisoformat(_normalize_date(to_date))
    if start > end:
        raise ValueError(f"from_date ({start}) > to_date ({end})")
    days: list[str] = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += dt.timedelta(days=1)
    return tuple(days)


def classify_zero_calendar_day(
    market: str,
    date: str,
    *,
    is_target_day: bool,
    symbols: "object",
    symbols_with_bars: "object",
) -> ZeroCalendarDayVerdict:
    """AM-6 fail-closed three-state matrix for one hk/us candidate day.

    ① target day, all-market zero bar → ``VERDICT_NOT_READY`` (the tool layer
    emits the retryable ``PAPER_DATA_NOT_READY`` envelope; data delays are
    absorbed by the RM retry chain).  ② mid-range day, all-market zero bar →
    ``VERDICT_MARKET_CLOSED_INFERRED`` + mandatory warning — never silently a
    ``non_trading_day`` (that reason is cn_a-only, CH calendar truth).  ③ any
    symbol has a bar → ``VERDICT_TRADING_DAY``; zero-bar symbols come back as
    ``suspended_symbols`` (engine rejects their orders ``suspended`` and
    values their positions carry-forward).

    ``symbols`` is the account universe (positions ∪ orders);
    ``symbols_with_bars`` comes from :func:`data.day_bar_availability`.
    cn_a is refused (ValueError) — ``market_closed_inferred`` is hk/us-only
    vocabulary.  An empty universe classifies as all-market zero bar (the
    matrix is literal; degenerate calls are the tool layer's concern).
    """
    if market not in _ZERO_CALENDAR_MARKETS:
        raise ValueError(f"zero-calendar classification is hk/us only, got market {market!r}")
    day = _normalize_date(date)
    universe = tuple(sorted({str(symbol) for symbol in symbols}))
    with_bars = frozenset(universe) & {str(symbol) for symbol in symbols_with_bars}
    if not with_bars:
        if is_target_day:
            return ZeroCalendarDayVerdict(day, VERDICT_NOT_READY)
        return ZeroCalendarDayVerdict(
            day, VERDICT_MARKET_CLOSED_INFERRED, warning=_MARKET_CLOSED_WARNING.format(date=day)
        )
    suspended = tuple(symbol for symbol in universe if symbol not in with_bars)
    return ZeroCalendarDayVerdict(day, VERDICT_TRADING_DAY, suspended_symbols=suspended)


class CalendarUnavailableError(RuntimeError):
    """A calendar query failed or did not establish every requested date."""


@dataclass(frozen=True)
class CalendarSnapshot:
    frame: "pd.DataFrame"

    def get_trade_calendar(self, start_date: str, end_date: str) -> "pd.DataFrame":
        return self.frame.copy()


def snapshot_calendar(client: TradeCalendarClient, start_date: str, end_date: str) -> CalendarSnapshot:
    """Read once; a missing row is unknown, never a confirmed market closure."""
    import pandas as pd

    try:
        frame = client.get_trade_calendar(start_date, end_date)
        observed = {}
        for row in frame.to_dict("records"):
            day = _normalize_date(row["cal_date"])
            if str(row["is_open"]) not in ("0", "1", "False", "True"):
                raise ValueError("invalid open flag")
            observed[day] = True
        required = {day.strftime("%Y-%m-%d") for day in pd.date_range(start_date, end_date)}
        if not required.issubset(observed):
            raise ValueError("incomplete date coverage")
        frame = frame.copy()
        frame["is_open"] = frame["is_open"].map(lambda value: int(str(value) in ("1", "True")))
        return CalendarSnapshot(frame)
    except Exception as exc:
        raise CalendarUnavailableError("Trading calendar query failed or has incomplete date coverage") from exc
