"""Public journal analysis must reject missing or invalid dates before filters."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.tools.trade_journal_tool import analyze_trade_journal


def _analyze(tmp_path, monkeypatch, rows, mode="full", filter_expr="", excel=False):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    path = tmp_path / ("journal.xlsx" if excel else "journal.csv")
    frame = pd.DataFrame(rows)
    if excel:
        frame.to_excel(path, index=False)
    else:
        frame.to_csv(path, index=False)
    return json.loads(analyze_trade_journal(str(path), mode, filter_expr))


def _row(dt, side="buy", symbol="AAPL"):
    return dict(datetime=dt, symbol=symbol, side=side, quantity=1, price=100, fee=1)


def _assert_date_error(result):
    assert result["status"] == "error"
    assert "date" in result["error"].lower()
    assert "correct" in result["error"].lower()
    assert set(result) == {"status", "error"}


@pytest.mark.parametrize("bad_date", ["", "not-a-date", "9999-01-01"])
@pytest.mark.parametrize("all_bad", [False, True])
def test_invalid_trade_dates_are_not_reported_as_normal_statistics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_date: str, all_bad: bool
):
    result = _analyze(
        tmp_path,
        monkeypatch,
        [_row(bad_date), _row(bad_date if all_bad else "2026-01-02", "sell")],
    )
    _assert_date_error(result)
    if bad_date:
        assert bad_date not in result["error"]
    assert str(tmp_path) not in result["error"]


@pytest.mark.parametrize("mode", ["full", "profile", "behavior", "strategy"])
def test_every_analysis_mode_checks_dates(tmp_path, monkeypatch, mode):
    _assert_date_error(_analyze(tmp_path, monkeypatch, [_row("")], mode=mode))


@pytest.mark.parametrize("dividend_only", [False, True])
def test_invalid_cash_event_date_also_blocks_analysis(
    tmp_path, monkeypatch, dividend_only
):
    dividend = dict(
        datetime="",
        symbol="AAPL",
        side="dividend",
        quantity=0,
        price=0,
        amount=5,
        fee=0,
    )
    rows = [] if dividend_only else [_row("2026-01-01"), _row("2026-01-02", "sell")]
    _assert_date_error(_analyze(tmp_path, monkeypatch, rows + [dividend]))


@pytest.mark.parametrize(
    "filter_expr", ["2026-01 to 2026-01", "symbol=AAPL", "market=us", "symbol=NONE"]
)
def test_filter_cannot_hide_invalid_date(tmp_path, monkeypatch, filter_expr):
    rows = [_row("2026-01-01"), _row("2026-01-02", "sell"), _row("", symbol="00700.HK")]
    _assert_date_error(_analyze(tmp_path, monkeypatch, rows, filter_expr=filter_expr))


@pytest.mark.parametrize("fmt", ["futu", "tonghuashun", "eastmoney"])
def test_broker_parser_outputs_get_same_validation(tmp_path, monkeypatch, fmt):
    if fmt == "futu":
        row = dict(Date="", Time="", Symbol="AAPL", Side="buy", Quantity=1, Price=100)
    elif fmt == "tonghuashun":
        row = {
            "成交时间": "",
            "证券代码": "600519",
            "操作": "买入",
            "成交数量": 1,
            "成交价格": 100,
        }
    else:
        row = {
            "成交日期": "",
            "成交时间": "",
            "股票代码": "600519",
            "买卖标志": "B",
            "成交数量": 1,
            "成交均价": 100,
        }
    _assert_date_error(_analyze(tmp_path, monkeypatch, [row]))


def test_xlsx_invalid_date_is_rejected(tmp_path, monkeypatch):
    _assert_date_error(_analyze(tmp_path, monkeypatch, [_row("")], excel=True))


@pytest.mark.parametrize(
    "dates,expected_range",
    [
        (["2026-01-01", "2026-01-02"], "2026-01-01 ~ 2026-01-02"),
        (["2026-01-01 10:00:00", "2026-01-02 10:00:00"], "2026-01-01 ~ 2026-01-02"),
        (["45321.375", "45322.375"], "2024-01-30 ~ 2024-01-31"),
    ],
)
def test_valid_date_formats_keep_normal_report(
    tmp_path, monkeypatch, dates, expected_range
):
    result = _analyze(tmp_path, monkeypatch, [_row(dates[0]), _row(dates[1], "sell")])
    assert result["status"] == "ok"
    assert result["date_range"] == expected_range
    assert result["profile"]["total_roundtrips"] == 1
    assert result["profile"]["total_pnl"] == -2


def test_valid_dividend_only_journal_is_accepted(tmp_path, monkeypatch):
    row = dict(
        datetime="2026-01-01",
        symbol="AAPL",
        side="dividend",
        quantity=0,
        price=0,
        amount=5,
        fee=0,
    )
    result = _analyze(tmp_path, monkeypatch, [row], mode="profile")
    assert result["status"] == "ok"
    assert result["profile"]["total_dividends"] == 5
