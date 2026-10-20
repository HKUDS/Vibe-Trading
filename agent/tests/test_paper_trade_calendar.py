"""Offline tests for the paper_trade calendar seam (AM-6 / VD-5).

cn_a: ClickHouse trade_calendar lookup through an INJECTABLE fake client —
recorded rows only, never the network (ClickHouse is unreachable anyway;
the plan raised HIL for live probes).  hk/us: the approved AM-6
zero-calendar design (G1 2026-10-19) — calendar lookups stay closed
(NotImplementedError); day verdicts flow through bar availability in
calendar.classify_zero_calendar_day instead.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.tools.paper_trade.calendar import is_trading_day, trading_days_in_range

_COLUMNS = ["exchange", "cal_date", "is_open", "pretrade_date"]


class FakeCalendarClient:
    """Returns recorded trade_calendar rows; captures requested ranges."""

    def __init__(self, rows: list[tuple[str, str, int]]) -> None:
        self.requested_ranges: list[tuple[str, str]] = []
        self._records = [
            {"exchange": exchange, "cal_date": cal_date, "is_open": is_open, "pretrade_date": ""}
            for exchange, cal_date, is_open in rows
        ]

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        self.requested_ranges.append((start_date, end_date))
        return pd.DataFrame(self._records, columns=_COLUMNS)


# A realistic cn_a week: Thu 10-15 .. Tue 10-20, weekend closed, plus the
# National Day holiday 2026-10-01.
_OCTOBER_ROWS: list[tuple[str, str, int]] = [
    ("SSE", "2026-10-01", 0),
    ("SSE", "2026-10-15", 1),
    ("SSE", "2026-10-16", 1),
    ("SSE", "2026-10-17", 0),
    ("SSE", "2026-10-18", 0),
    ("SSE", "2026-10-19", 1),
    ("SSE", "2026-10-20", 1),
]


@pytest.fixture()
def cn_a_client() -> FakeCalendarClient:
    return FakeCalendarClient(_OCTOBER_ROWS)


def test_open_trading_day_is_true(cn_a_client: FakeCalendarClient) -> None:
    assert is_trading_day(cn_a_client, "cn_a", "2026-10-20") is True


def test_weekend_row_is_false(cn_a_client: FakeCalendarClient) -> None:
    assert is_trading_day(cn_a_client, "cn_a", "2026-10-18") is False


def test_holiday_row_is_false(cn_a_client: FakeCalendarClient) -> None:
    assert is_trading_day(cn_a_client, "cn_a", "2026-10-01") is False


def test_missing_row_fails_closed_to_false(cn_a_client: FakeCalendarClient) -> None:
    # The table is the truth source: a date it does not cover is NOT a
    # confirmed trading day.
    assert is_trading_day(cn_a_client, "cn_a", "2026-12-25") is False


def test_multi_exchange_rows_aggregate_as_any_open() -> None:
    client = FakeCalendarClient(
        [("SSE", "2026-10-20", 1), ("SZSE", "2026-10-20", 0), ("SSE", "2026-10-19", 0), ("SZSE", "2026-10-19", 0)]
    )
    assert is_trading_day(client, "cn_a", "2026-10-20") is True
    assert is_trading_day(client, "cn_a", "2026-10-19") is False


def test_trading_days_in_range_enumerates_ascending(cn_a_client: FakeCalendarClient) -> None:
    days = trading_days_in_range(cn_a_client, "cn_a", "2026-10-15", "2026-10-20")
    assert days == ("2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20")


def test_range_is_passed_through_to_the_client(cn_a_client: FakeCalendarClient) -> None:
    trading_days_in_range(cn_a_client, "cn_a", "2026-10-15", "2026-10-20")
    assert cn_a_client.requested_ranges == [("2026-10-15", "2026-10-20")]


def test_single_day_lookup_queries_that_day_only(cn_a_client: FakeCalendarClient) -> None:
    is_trading_day(cn_a_client, "cn_a", "2026-10-20")
    assert cn_a_client.requested_ranges == [("2026-10-20", "2026-10-20")]


def test_out_of_range_rows_from_a_sloppy_client_are_clamped() -> None:
    client = FakeCalendarClient([("SSE", "2026-10-20", 1), ("SSE", "2026-11-02", 1)])
    assert trading_days_in_range(client, "cn_a", "2026-10-19", "2026-10-21") == ("2026-10-20",)


def test_yyyymmdd_cal_date_spelling_is_normalized() -> None:
    # The stored cal_date spelling is unverified while CH is unreachable
    # (Step 0 DD-5 live recheck pending); tushare-lineage exports use
    # YYYYMMDD. Both spellings must serve the same verdicts.
    client = FakeCalendarClient([("SSE", "20261020", 1), ("SSE", "20261018", 0)])
    assert is_trading_day(client, "cn_a", "2026-10-20") is True
    assert is_trading_day(client, "cn_a", "2026-10-18") is False
    assert trading_days_in_range(client, "cn_a", "2026-10-18", "2026-10-20") == ("2026-10-20",)


def test_unrecognized_date_format_fails_closed(cn_a_client: FakeCalendarClient) -> None:
    with pytest.raises(ValueError, match="unrecognized calendar date"):
        is_trading_day(cn_a_client, "cn_a", "2026/10/20")


@pytest.mark.parametrize("market", ["hk", "us"])
def test_hk_and_us_calendar_lookups_stay_closed_by_am6_design(
    cn_a_client: FakeCalendarClient, market: str
) -> None:
    # AM-6 zero-calendar design, APPROVED at G1 (2026-10-19): hk/us day
    # verdicts come from bar availability (calendar.classify_zero_calendar_day
    # over the data layer's facts), never from a calendar lookup — the repo
    # carries no hk/us calendar and the zero-new-dependency red line forbids
    # one.  These lookups staying NotImplementedError IS the approved
    # fail-closed behavior (tested via the T2/T3 matrix seams), not a gap.
    with pytest.raises(NotImplementedError, match="zero-calendar"):
        is_trading_day(cn_a_client, market, "2026-10-20")
    with pytest.raises(NotImplementedError, match="zero-calendar"):
        trading_days_in_range(cn_a_client, market, "2026-10-15", "2026-10-20")


def test_unknown_market_raises_value_error(cn_a_client: FakeCalendarClient) -> None:
    with pytest.raises(ValueError, match="unknown market"):
        is_trading_day(cn_a_client, "crypto", "2026-10-20")


def test_lookups_are_deterministic(cn_a_client: FakeCalendarClient) -> None:
    first = trading_days_in_range(cn_a_client, "cn_a", "2026-10-01", "2026-10-20")
    second = trading_days_in_range(cn_a_client, "cn_a", "2026-10-01", "2026-10-20")
    assert first == second
