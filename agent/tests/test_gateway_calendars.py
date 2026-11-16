"""Independent session-boundary examples, with no real market-price assertions."""

import pandas as pd
import pytest

from src.data_gateway.calendars import CalendarCoverageError, validate
from src.data_gateway.history_router import fetch_chunk


def rows(stamps):
    return [{"trade_date": str(t), "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100} for t in stamps]


def test_us_thanksgiving_is_closed_and_half_day_stops_at_1300_eastern():
    assert validate([], "us_equity", "2026-11-26", "2026-11-26", "1D", {})[1]["coverage_verified"]
    stamps = pd.date_range("2026-11-27 14:30", "2026-11-27 18:00", freq="1min", inclusive="left")
    values, meta = validate(rows(stamps), "us_equity", "2026-11-27", "2026-11-27", "1m", {"source": "yahoo"})
    assert len(values) == meta["expected_rows"] == 210
    assert meta["calendar"] == "XNYS" and meta["coverage_verified"]
    with pytest.raises(CalendarCoverageError):
        validate(
            rows(stamps.append(pd.DatetimeIndex(["2026-11-27 18:00"]))),
            "us_equity",
            "2026-11-27",
            "2026-11-27",
            "1m",
            {"source": "yahoo"},
        )


@pytest.mark.parametrize("day,opening,closing", [("2026-03-06", "14:30", "21:00"), ("2026-03-09", "13:30", "20:00")])
def test_us_dst_changes_utc_grid_without_changing_session_length(day, opening, closing):
    stamps = pd.date_range(day + " " + opening, day + " " + closing, freq="5min", inclusive="left")
    assert validate(rows(stamps), "us_equity", day, day, "5m", {"source": "yahoo"})[1]["expected_rows"] == 78


def test_hong_kong_lunch_is_not_missing_bars():
    stamps = pd.date_range("2026-11-02 01:30", "2026-11-02 04:00", freq="5min", inclusive="left").append(
        pd.date_range("2026-11-02 05:00", "2026-11-02 08:00", freq="5min", inclusive="left")
    )
    assert (
        validate(rows(stamps), "hk_equity", "2026-11-02", "2026-11-02", "5m", {"source": "yahoo"})[1]["expected_rows"]
        == 66
    )
    with pytest.raises(CalendarCoverageError, match="extra=1"):
        validate(
            rows(stamps.append(pd.DatetimeIndex(["2026-11-02 04:30"]))),
            "hk_equity",
            "2026-11-02",
            "2026-11-02",
            "5m",
            {"source": "yahoo"},
        )


@pytest.mark.parametrize("damage", ["internal", "tail", "duplicate", "wrong_zone"])
def test_incomplete_or_wrong_timezone_series_is_never_promoted(damage):
    stamps = pd.date_range("2026-11-12 14:30", "2026-11-12 21:00", freq="1min", inclusive="left")
    value = rows(stamps)
    if damage == "internal":
        del value[120]
    elif damage == "tail":
        value.pop()
    elif damage == "duplicate":
        value.append(dict(value[-1]))
    else:
        value = rows(stamps - pd.Timedelta(hours=5))
    with pytest.raises(CalendarCoverageError):
        validate(value, "us_equity", "2026-11-12", "2026-11-12", "1m", {"source": "yahoo"})


def test_close_point_is_excluded_explicitly_but_real_after_hours_trade_is_not_hidden():
    values = rows(pd.date_range("2026-11-13 14:30", "2026-11-13 21:00", freq="1min", inclusive="left"))
    point = {"trade_date": "2026-11-13 21:00", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 0}
    kept, meta = validate(values + [point], "us_equity", "2026-11-13", "2026-11-13", "1m", {"source": "yahoo"})
    assert len(kept) == 390 and len(values) == 390
    assert meta["excluded_source_points"] == [
        {"time": point["trade_date"], "reason": "zero_volume_point_at_session_close_not_a_bar_open"}
    ]
    with pytest.raises(CalendarCoverageError):
        validate(values + [point | {"volume": 1}], "us_equity", "2026-11-13", "2026-11-13", "1m", {"source": "yahoo"})


def test_unknown_timestamp_semantics_stay_unverified_and_observed_timezone_works():
    value = rows(pd.date_range("2026-11-12 09:30", "2026-11-12 16:00", freq="5min", inclusive="left"))
    assert not validate(value, "us_equity", "2026-11-12", "2026-11-12", "5m", {"source": "yfinance"})[1][
        "coverage_verified"
    ]
    assert validate(
        value,
        "us_equity",
        "2026-11-12",
        "2026-11-12",
        "5m",
        {"source": "yfinance", "timezone": "America/New_York", "timestamp_basis": "bar_open"},
    )[1]["coverage_verified"]


def test_daily_weekly_monthly_exact_requested_session_endpoints():
    for market in ("us_equity", "hk_equity", "ca_equity", "uk_equity"):
        values = rows(pd.bdate_range("2026-11-02", "2026-11-13"))
        assert validate(values, market, "2026-11-02", "2026-11-13", "1D", {})[1]["coverage_verified"]
        with pytest.raises(CalendarCoverageError, match="missing=1"):
            validate(values[:-1], market, "2026-11-02", "2026-11-13", "1D", {})
        assert validate(rows(["2026-11-06", "2026-11-13"]), market, "2026-11-02", "2026-11-13", "1W", {})[1][
            "coverage_verified"
        ]
        assert validate(rows(["2026-10-30", "2026-11-13"]), market, "2026-10-15", "2026-11-13", "1M", {})[1][
            "coverage_verified"
        ]


def test_closed_interval_needs_no_source_and_does_not_fabricate_price(monkeypatch):
    monkeypatch.setattr("src.data_gateway.get_gateway", lambda: pytest.fail("Closed session needs no source"))
    values, meta = fetch_chunk("AAPL.US", "2026-11-14", "2026-11-15", "1m")
    assert values == [] and meta["source"] is None and meta["coverage_verified"]
    assert meta["coverage"] == "exchange_closed_interval"
