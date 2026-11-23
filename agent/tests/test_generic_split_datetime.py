"""Separate date/time columns must preserve chronology and FIFO economics."""

from __future__ import annotations

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


import json
from pathlib import Path

import pandas as pd
import pytest

from src.tools.trade_journal_parsers import parse_generic
from src.tools.trade_journal_tool import analyze_trade_journal


def _record(**dates):
    frame = pd.DataFrame(
        [{"symbol": "AAPL", "side": "buy", "quantity": 1, "price": 100, **dates}]
    )
    return parse_generic(frame)[0]


@pytest.mark.parametrize(
    "date,time,expected",
    [
        ("2024-01-30", "09:30:15", "2024-01-30 09:30:15"),
        ("45321", "09:30:15", "2024-01-30 09:30:15"),
        (45321, 0.375, "2024-01-30 09:00:00"),
        ("45321.0", "0.375", "2024-01-30 09:00:00"),
        ("2024-01-30", "0.375", "2024-01-30 09:00:00"),
        ("2024-01-30", 0.0, "2024-01-30 00:00:00"),
        ("2024-01-30", "", "2024-01-30 00:00:00"),
        ("2024-01-30", None, "2024-01-30 00:00:00"),
        ("2024-01-30", float("nan"), "2024-01-30 00:00:00"),
    ],
)
def test_split_date_time_cells(date, time, expected):
    assert _record(date=date, time=time).datetime == expected


def test_complete_datetime_takes_priority_over_date_and_time():
    record = _record(datetime="2024-01-30 14:25:00", date="2020-01-01", time="09:30:00")
    assert record.datetime == "2024-01-30 14:25:00"


@pytest.mark.parametrize("column", ["datetime", "date", "time"])
def test_single_datetime_columns_keep_existing_behavior(column):
    assert _record(**{column: "2024-01-30 14:25:00"}).datetime == (
        "2024-01-30 14:25:00"
    )


@pytest.mark.parametrize("date", ["", "not-a-date"])
def test_bad_split_date_does_not_turn_clock_into_todays_date(date):
    assert pd.isna(
        pd.to_datetime(_record(date=date, time="09:30:00").datetime, errors="coerce")
    )


@pytest.mark.parametrize("reverse_rows", [False, True])
def test_split_csv_preserves_net_winners_and_date_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reverse_rows: bool
):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    rows = [
        "2026-01-01,15:00:00,AAPL,buy,1,100,1",
        "2026-01-02,09:00:00,AAPL,sell,1,105,1",
        "2026-01-03,10:00:00,AAPL,buy,1,110,1",
        "2026-01-04,11:00:00,AAPL,sell,1,120,1",
        "2026-01-05,12:00:00,MSFT,buy,1,50,1",
        "2026-01-06,13:00:00,MSFT,sell,1,48,1",
    ]
    path = tmp_path / "journal.csv"
    path.write_text(
        "Date,Time,Symbol,Side,Qty,Price,Fee\n"
        + "\n".join(reversed(rows) if reverse_rows else rows)
        + "\n",
        encoding="utf-8",
    )

    result = json.loads(analyze_trade_journal(str(path), "profile", roots=FileRoots.from_config(get_env_config().api)))
    assert result["status"] == "ok"
    assert result["format_detected"] == "generic"
    assert result["date_range"] == "2026-01-01 ~ 2026-01-06"
    profile = result["profile"]
    # Hand calculation: (105-100)-2=3; (120-110)-2=8; (48-50)-2=-4.
    assert [r["pnl"] for r in profile["roundtrips_sample"]] == [3, 8, -4]
    assert all(r["side"] == "long" for r in profile["roundtrips_sample"])
    assert profile["total_pnl"] == 7
    assert profile["win_rate"] == 0.6667
    assert profile["profit_loss_ratio"] == 1.38  # ((3 + 8) / 2) / 4
    assert [r["hold_days"] for r in profile["roundtrips_sample"]] == [0.75, 1.04, 1.04]

    filtered = json.loads(
        analyze_trade_journal(str(path), "profile", "2026-01 to 2026-01", roots=FileRoots.from_config(get_env_config().api))
    )
    assert filtered["total_records"] == 6
    assert filtered["profile"]["win_rate"] == 0.6667
