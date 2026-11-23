"""Offline B3: calendar/FX causality, official lots and actual execution costs."""

from pathlib import Path

import pandas as pd
import pytest

from backtest.engines.composite import CompositeEngine
from backtest.engines.global_equity import GlobalEquityEngine
from backtest.market_layer import (
    hk_equity_to_usd,
    hk_stamp_duty,
    load_hk_board_lots,
    load_hkd_fx_observations,
    local_and_usd_returns,
    previous_close_fx,
)
from src.data_gateway.calendars import CalendarCoverageError, schedule, validate

LOTS = Path(__file__).parents[1] / "backtest/data/hk_board_lots_20261112.csv"


@pytest.mark.parametrize(
    "day",
    [
        "2026-10-01",
        "2016-08-02",
        "2016-10-21",
        "2017-08-23",
        "2023-07-17",
        "2023-09-01",
        "2023-09-08",
    ],
)
def test_hk_holiday_and_historical_weather_closures(day):
    assert schedule("hk_equity", day, day)[2].empty


def test_hk_weather_late_open_has_no_fictitious_lunch():
    row = schedule("hk_equity", "2023-10-09", "2023-10-09")[2].iloc[0]
    assert row["open"] == pd.Timestamp("2023-10-09T06:00:00Z")
    assert pd.isna(row["break_start"]) and pd.isna(row["break_end"])


def test_hk_post_reform_weather_does_not_imply_a_closure():
    # Typhoon Toraji, 14 Nov 2024: ordinary severe weather trading now continues.
    # The calendar contains the session; no universal T8/black-rain switch is used.
    assert len(schedule("hk_equity", "2024-11-14", "2024-11-14")[2]) == 1


def test_hk_halfday_and_nyse_alignment_available():
    row = schedule("hk_equity", "2026-12-24", "2026-12-24")[2].iloc[0]
    assert row["close"] == pd.Timestamp("2026-12-24T04:00:00Z")
    assert schedule("us_equity", "2026-10-01", "2026-10-01")[0] == "XNYS"


def test_lunch_bar_rejected_by_actual_calendar_validator():
    # Complete valid hourly continuous-session bar opens, plus an invalid lunch bar.
    stamps = ["01:30", "02:30", "03:30", "05:00", "06:00", "07:00", "04:30"]
    rows = [{"time": f"2026-11-12T{stamp}:00Z"} for stamp in stamps]
    with pytest.raises(CalendarCoverageError, match="extra=1"):
        validate(
            rows,
            "hk_equity",
            "2026-11-12",
            "2026-11-12",
            "1H",
            {"timezone": "UTC", "timestamp_basis": "bar_open"},
        )
    _, meta = validate(
        rows[:-1],
        "hk_equity",
        "2026-11-12",
        "2026-11-12",
        "1H",
        {"timezone": "UTC", "timestamp_basis": "bar_open"},
    )
    assert (
        meta["coverage_verified"] and "not exhaustive" in meta["calendar_limitations"]
    )


def fx_quotes():
    return pd.DataFrame(
        {
            "close_at": pd.to_datetime(
                ["2026-10-29T22:00Z", "2026-10-30T22:00Z", "2026-11-02T22:00Z"]
            ),
            "available_at": pd.to_datetime(
                ["2026-10-29T22:05Z", "2026-10-30T22:05Z", "2026-11-02T22:05Z"]
            ),
            "rate": [7.8, 7.9, 8.0],
        }
    )


def test_fx_previous_available_close_and_weekend_no_future_rate():
    at = pd.to_datetime(["2026-10-30T08:00Z", "2026-11-02T08:00Z"])
    got = previous_close_fx(at, fx_quotes())
    assert got["rate"].tolist() == [7.8, 7.9]
    assert (got["close_at"].array < at).all()
    assert (got["available_at"].array < at).all()


def test_fx_unpublished_close_never_used_even_at_its_publication_instant():
    got = previous_close_fx(pd.to_datetime(["2026-10-30T22:05Z"]), fx_quotes())
    assert got.iloc[0]["rate"] == 7.8


def test_fx_conversion_is_division_and_returns_include_fx():
    values = pd.Series(
        [780.0, 790.0], index=pd.to_datetime(["2026-10-30T08:00Z", "2026-11-02T08:00Z"])
    )
    result = local_and_usd_returns(values, fx_quotes())
    assert result["value_usd"].tolist() == pytest.approx([100, 100])
    assert result["return_usd"].iloc[1] == pytest.approx(0)
    assert result["return_local"].iloc[1] == pytest.approx(790 / 780 - 1)


@pytest.mark.parametrize("at", ["2026-10-29T08:00Z", "2026-11-15T08:00Z"])
def test_fx_missing_or_stale_is_an_error(at):
    with pytest.raises(ValueError, match="Missing or stale"):
        previous_close_fx(pd.to_datetime([at]), fx_quotes())


@pytest.mark.parametrize("bad_rate", [0, -1, float("nan"), float("inf")])
def test_fx_invalid_rates_rejected(bad_rate):
    quotes = fx_quotes()
    quotes.loc[0, "rate"] = bad_rate
    with pytest.raises(ValueError, match="finite and positive"):
        previous_close_fx(pd.to_datetime(["2026-10-30T08:00Z"]), quotes)


def test_fx_cannot_claim_availability_before_close_or_use_naive_instants():
    quotes = fx_quotes()
    quotes.loc[0, "available_at"] = pd.Timestamp("2026-10-29T21:00Z")
    with pytest.raises(ValueError, match="before their close"):
        previous_close_fx(pd.to_datetime(["2026-10-30T08:00Z"]), quotes)
    with pytest.raises(ValueError, match="timezone-aware"):
        previous_close_fx(pd.to_datetime(["2026-10-30"]), fx_quotes())


@pytest.mark.parametrize(
    "day,expected",
    [
        ("2021-07-30", 11),
        ("2021-08-01", 14),
        ("2023-11-16", 14),
        ("2023-11-17", 11),
    ],
)
def test_duty_date_boundaries_and_whole_dollar_ceiling(day, expected):
    assert hk_stamp_duty(100, 100.01, day) == expected


@pytest.mark.parametrize(
    "direction,is_open", [(1, True), (1, False), (-1, True), (-1, False)]
)
def test_actual_engine_lot_rounding_and_bilateral_duty_hand_calculation(
    direction, is_open
):
    config = {
        "initial_cash": 100000,
        "hk_lot_sizes_file": str(LOTS),
        "hk_commission": 0,
        "hk_levy": 0,
        "hk_settlement": 0,
    }
    engine = GlobalEquityEngine(config, market="hk")
    engine._active_symbol = "700.HK"
    assert engine.round_size(250, 100.01) == 200
    assert engine.round_size(255, 100.01) == 200  # Tencent's dated board lot is 100.
    engine._bar_ts = pd.Timestamp("2023-11-16")
    assert (
        engine.calc_commission(200, 100.01, direction, is_open) == 27
    )  # ceil(20002*.0013)
    engine._bar_ts = pd.Timestamp("2023-11-17")
    assert (
        engine.calc_commission(200, 100.01, direction, is_open) == 21
    )  # ceil(20002*.001)
    assert not engine.hk_lot_snapshot["historical_lots_verified"]


def test_lot_file_is_dated_95_name_source_and_unknown_lot_warns(caplog):
    lots, meta = load_hk_board_lots(LOTS)
    assert len(lots) == 95 and lots["0005.HK"] == 400
    assert meta["retrieved_at"].startswith("2026-11-12")
    engine = GlobalEquityEngine({"hk_lot_sizes_file": str(LOTS)}, market="hk")
    engine._active_symbol = "1234.HK"
    assert engine.round_size(255, 1) == 255
    assert engine.lot_assumptions == {"1234.HK": 1}
    assert "default 1-share lot" in caplog.text


def test_explicit_strict_lot_policy_still_fails_closed():
    engine = GlobalEquityEngine(
        {"hk_lot_sizes_file": str(LOTS), "hk_require_lot_sizes": True}, market="hk"
    )
    engine._active_symbol = "1234.HK"
    with pytest.raises(ValueError, match="board lot missing"):
        engine.round_size(1000, 1)


def test_lot_alias_duplicates_rejected(tmp_path):
    path = tmp_path / "lots.csv"
    path.write_text(
        "symbol,board_lot,pulled_at,source,source_sha256\n700.HK,100,2026-11-12,https://example.test,abc\n0700.HK,100,2026-11-12,https://example.test,abc\n"
    )
    with pytest.raises(ValueError, match="Duplicate"):
        load_hk_board_lots(path)


def test_composite_syncs_timestamp_before_hk_commission_without_changing_india_rules():
    config = {
        "initial_cash": 100000,
        "codes": ["0700.HK"],
        "hk_commission": 0,
        "hk_levy": 0,
        "hk_settlement": 0,
    }
    engine = CompositeEngine(config, config["codes"])
    engine._active_symbol = "0700.HK"
    for day, expected in [("2023-11-16", 14), ("2023-11-17", 11)]:
        engine._bar_ts = pd.Timestamp(day)
        assert engine.calc_commission(100, 100.01, 1, True) == expected


def test_explicit_stamp_override_retained_but_still_rounded():
    engine = GlobalEquityEngine({"hk_stamp_tax": 0}, market="hk")
    engine._bar_ts = pd.Timestamp("2022-01-05")
    assert hk_stamp_duty(100, 100.01, "2022-01-05", rate_override=0) == 0
    assert engine._hk_stamp_tax_override == 0


def test_invalid_fx_age_and_duplicate_close_fail_closed():
    with pytest.raises(ValueError, match="maximum age"):
        previous_close_fx(
            pd.to_datetime(["2026-10-30T08:00Z"]), fx_quotes(), max_age=pd.NaT
        )
    quotes = pd.concat([fx_quotes(), fx_quotes().iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="unique"):
        previous_close_fx(pd.to_datetime(["2026-10-30T08:00Z"]), quotes)


def test_duty_out_of_supported_history_requires_override():
    with pytest.raises(ValueError, match="before 2001"):
        hk_stamp_duty(100, 100.01, "2000-01-05")
    assert hk_stamp_duty(100, 100.01, "2000-01-05", rate_override=0.001125) == 12


@pytest.mark.parametrize("composite", [False, True])
def test_actual_hk_execution_rejects_lunch_and_terminal_lunch_liquidation(composite):
    config = {"codes": ["0700.HK"], "interval": "1m"}
    engine = (
        CompositeEngine(config, config["codes"])
        if composite
        else GlobalEquityEngine(config, market="hk")
    )
    bar = pd.Series({"open": 100, "close": 100})
    for stamp, allowed in [
        ("2026-11-12T03:59:00Z", True),
        ("2026-11-12T04:00:00Z", False),
        ("2026-11-12T04:30:00Z", False),
        ("2026-11-12T05:00:00Z", True),
        ("2026-11-12T08:00:00Z", False),
    ]:
        engine._bar_ts = pd.Timestamp(stamp)
        assert engine.can_execute("0700.HK", 1, bar) is allowed
        assert engine.can_liquidate_at_end("0700.HK", pd.Timestamp(stamp)) is allowed


@pytest.mark.parametrize(
    "day,allowed",
    [
        ("2026-10-01", False),
        ("2023-09-08", False),
        ("2025-09-24", True),
    ],
)
def test_daily_execution_uses_holidays_and_historical_weather(day, allowed):
    engine = GlobalEquityEngine({}, market="hk")
    engine._bar_ts = pd.Timestamp(day)
    assert engine.can_execute("0700.HK", 1, pd.Series(dtype=float)) is allowed


@pytest.mark.parametrize("day", ["2026-12-24", "2026-12-31", "2026-02-16"])
def test_hk_halfday_afternoon_fills_rejected_and_naive_intraday_is_local(day):
    engine = GlobalEquityEngine({"interval": "1m"}, market="hk")
    for stamp, allowed in [(f"{day} 11:59", True), (f"{day} 13:01", False)]:
        engine._bar_ts = pd.Timestamp(stamp)
        assert engine.can_execute("0700.HK", 1, pd.Series(dtype=float)) is allowed


def test_actual_fill_ledger_contains_no_lunch_fills():
    dates = pd.to_datetime(
        [
            "2026-11-12T03:30Z",
            "2026-11-12T04:30Z",
            "2026-11-12T05:00Z",
            "2026-11-12T05:30Z",
        ]
    )
    config = {
        "initial_cash": 100000,
        "interval": "1m",
        "hk_lot_sizes": {"0700.HK": 100},
    }
    engine = GlobalEquityEngine(config, market="hk")
    frame = pd.DataFrame({"open": 100.0, "close": 100.0}, index=dates)
    targets = pd.DataFrame({"0700.HK": [0.0, 0.5, 0.5, 0.5]}, index=dates)
    engine._execute_bars(
        dates,
        {"0700.HK": frame},
        frame[["close"]].rename(columns={"close": "0700.HK"}),
        targets,
        ["0700.HK"],
    )
    assert engine.fill_records
    assert not any(fill.timestamp == dates[1] for fill in engine.fill_records)
    assert any(
        fill.action == "open" and fill.timestamp == dates[2]
        for fill in engine.fill_records
    )


def fx_daily_policy(label, provenance):
    """Synthetic fixture: daily close/publication instants known from its source."""
    assert provenance["source"] == "synthetic"
    day = pd.Timestamp(label).tz_localize("UTC")
    return day + pd.Timedelta(hours=22), day + pd.Timedelta(hours=22, minutes=5)


def fx_daily_fetcher(**kwargs):
    assert kwargs["codes"] == ["HKD=X"]
    assert kwargs["source"] == "yfinance" and kwargs["interval"] == "1D"
    assert (
        kwargs["as_frames"] and kwargs["include_provenance"] and kwargs["max_rows"] == 0
    )
    return {
        "HKD=X": pd.DataFrame(
            {"close": [7.8, 7.9, 8.0]},
            index=pd.to_datetime(["2026-10-29", "2026-10-30", "2026-11-02"]),
        ),
        "_provenance": {
            "HKD=X": {"source": "synthetic", "timestamp_basis": "session_date"}
        },
    }


def test_loader_to_hk_session_usd_curve_carries_prior_fx_without_lookahead():
    values = pd.Series(
        [780.0, 790.0], index=pd.to_datetime(["2026-10-30T08:00Z", "2026-11-02T08:00Z"])
    )
    result = hk_equity_to_usd(
        values, availability_policy=fx_daily_policy, fetcher=fx_daily_fetcher
    )
    assert result["rate"].tolist() == [7.8, 7.9]
    assert result["value_usd"].tolist() == pytest.approx([100.0, 100.0])
    assert result["return_usd"].iloc[1] == pytest.approx(0.0)
    assert result.attrs["units"] == "HKD_per_USD"
    assert result.attrs["availability_policy"] == "fx_daily_policy"
    assert result.attrs["publication_times_certified"] is False


def test_loader_fx_requires_policy_and_never_backfills_first_missing_rate():
    with pytest.raises(ValueError, match="explicit publication-time"):
        load_hkd_fx_observations(
            "2026-10-29",
            "2026-11-02",
            availability_policy=None,
            fetcher=fx_daily_fetcher,
        )
    values = pd.Series([780.0], index=pd.to_datetime(["2026-10-29T08:00Z"]))
    with pytest.raises(ValueError, match="Missing or stale"):
        hk_equity_to_usd(
            values, availability_policy=fx_daily_policy, fetcher=fx_daily_fetcher
        )


def test_fx_loader_cannot_fabricate_a_timestamp_or_accept_missing_data():
    with pytest.raises(ValueError, match="timezone-aware"):
        load_hkd_fx_observations(
            "2026-10-29",
            "2026-11-02",
            availability_policy=lambda label, _: (label, label),
            fetcher=fx_daily_fetcher,
        )
    with pytest.raises(ValueError, match="unavailable"):
        load_hkd_fx_observations(
            "2026-10-29",
            "2026-11-02",
            availability_policy=fx_daily_policy,
            fetcher=lambda **_: {},
        )


def test_hk_usd_curve_requires_actual_trading_sessions():
    values = pd.Series([780.0], index=pd.to_datetime(["2026-10-31T08:00Z"]))
    with pytest.raises(ValueError, match="HK trading sessions"):
        hk_equity_to_usd(
            values, availability_policy=fx_daily_policy, fetcher=fx_daily_fetcher
        )


def test_hsi_absence_audit_distinguishes_weather_candidates_from_provider_gaps():
    from src.data_gateway.hk_sessions import audit_hsi_session_coverage

    frame = pd.DataFrame({"close": [100.0]}, index=pd.to_datetime(["2023-09-04"]))
    report = audit_hsi_session_coverage(
        frame, "2023-09-01", "2023-09-05", provenance={"source": "synthetic"}
    )
    assert report["unverified_pre_reform_closure_candidates"] == ["2023-09-05"]
    assert not report["coverage_verified"]
    # Sep 1 is already a sourced full closure, not a silently inferred data gap.
    assert "2023-09-01" not in report["unverified_pre_reform_closure_candidates"]
    report = audit_hsi_session_coverage(
        frame.iloc[:0], "2025-09-24", "2025-09-24", provenance={"source": "synthetic"}
    )
    assert report["post_reform_data_gaps"] == ["2025-09-24"]
    assert not report["unverified_pre_reform_closure_candidates"]


def test_weather_inventory_is_sourced_and_reform_ignores_new_weather_overrides(
    monkeypatch,
):
    from src.data_gateway import hk_sessions

    inventory = hk_sessions.weather_closure_inventory()
    assert all(row["source"].startswith("https://") for row in inventory)
    assert {row["session"] for row in inventory} == {"morning", "full"}
    monkeypatch.setitem(
        hk_sessions.FULL_CLOSURES, "2025-09-24", "https://example.test/weather"
    )
    assert len(schedule("hk_equity", "2025-09-24", "2025-09-24")[2]) == 1
