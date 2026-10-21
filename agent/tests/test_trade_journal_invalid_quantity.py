"""Public journal analysis must reject invalid buy/sell quantities."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.tools.trade_journal_tool import analyze_trade_journal


def _row(side="buy", quantity=1, price=100, symbol="AAPL", day=1, fee=1):
    return dict(
        datetime=f"2026-01-{day:02d}",
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        fee=fee,
    )


def _analyze(tmp_path, monkeypatch, rows, mode="full", filter_expr="", excel=False):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    path = tmp_path / ("journal.xlsx" if excel else "journal.csv")
    frame = pd.DataFrame(rows)
    if excel:
        frame.to_excel(path, index=False)
    else:
        frame.to_csv(path, index=False)
    return json.loads(analyze_trade_journal(str(path), mode, filter_expr))


def _assert_quantity_error(result, tmp_path):
    assert set(result) == {"status", "error"}
    assert result["status"] == "error"
    assert "quantit" in result["error"].lower()
    assert "correct" in result["error"].lower()
    assert str(tmp_path) not in result["error"]
    assert "private-bad-value" not in result["error"]


@pytest.mark.parametrize("bad", ["", "private-bad-value", "0", "-1", "NaN", "Infinity"])
@pytest.mark.parametrize("side", ["buy", "sell"])
def test_ac2_invalid_quantity_cannot_be_ignored(tmp_path, monkeypatch, bad, side):
    rows = [_row(), _row("sell", price=110, day=2), _row(side, bad, day=3)]
    _assert_quantity_error(_analyze(tmp_path, monkeypatch, rows), tmp_path)


def test_ac2_missing_quantity_column(tmp_path, monkeypatch):
    row = _row()
    row.pop("quantity")
    _assert_quantity_error(_analyze(tmp_path, monkeypatch, [row]), tmp_path)


@pytest.mark.parametrize("mode", ["full", "profile", "behavior", "strategy"])
def test_ac3_all_modes_check_quantity(tmp_path, monkeypatch, mode):
    _assert_quantity_error(
        _analyze(tmp_path, monkeypatch, [_row(quantity=0)], mode=mode), tmp_path
    )


@pytest.mark.parametrize(
    "expr", ["2026-01 to 2026-01", "symbol=AAPL", "market=us", "symbol=NONE"]
)
def test_ac3_filter_cannot_hide_bad_quantity(tmp_path, monkeypatch, expr):
    bad = _row(quantity=0, symbol="00700.HK")
    bad["datetime"] = "2026-02-01"
    _assert_quantity_error(
        _analyze(tmp_path, monkeypatch, [_row(), bad], filter_expr=expr), tmp_path
    )


def test_ac5_excel_invalid_quantity(tmp_path, monkeypatch):
    _assert_quantity_error(
        _analyze(tmp_path, monkeypatch, [_row(quantity="bad")], excel=True), tmp_path
    )


@pytest.mark.parametrize("fmt", ["tonghuashun", "eastmoney", "futu"])
def test_ac5_broker_quantities_checked(tmp_path, monkeypatch, fmt):
    if fmt == "tonghuashun":
        row = {
            "成交时间": "2026-01-01",
            "证券代码": "600519",
            "操作": "买入",
            "成交数量": "bad",
            "成交价格": 100,
        }
    elif fmt == "eastmoney":
        row = {
            "成交日期": "20260101",
            "成交时间": "10:00:00",
            "股票代码": "600519",
            "买卖标志": "B",
            "成交数量": "bad",
            "成交均价": 100,
        }
    else:
        row = dict(
            Date="2026-01-01", Symbol="AAPL", Side="buy", Quantity="bad", Price=100
        )
    _assert_quantity_error(_analyze(tmp_path, monkeypatch, [row]), tmp_path)


@pytest.mark.parametrize("alias", ["quantity", "qty", "size", "volume"])
def test_ac4_quantity_aliases_and_fractional_fills(tmp_path, monkeypatch, alias):
    # 0.25 * (110 - 100) - two fees of 0.1 = 2.30.
    rows = [_row(quantity=0.25, fee=0.1), _row("sell", 0.25, 110, day=2, fee=0.1)]
    for row in rows:
        row[alias] = row.pop("quantity")
    result = _analyze(tmp_path, monkeypatch, rows)
    assert result["status"] == "ok"
    assert result["profile"]["total_pnl"] == pytest.approx(2.3)
    assert result["profile"]["total_roundtrips"] == 1


@pytest.mark.parametrize(
    "fills,expected",
    [
        ([("sell", 1, 110, 1), ("buy", 1, 100, 1)], 8),
        ([("buy", 2, 100, 1), ("sell", 1, 110, 1), ("sell", 1, 90, 1)], -3),
        ([("buy", 1, 100, 1), ("sell", 2, 110, 2), ("buy", 1, 105, 1)], 11),
        ([("buy", 1, 100, -1), ("sell", 1, 110, -1)], 12),
    ],
)
def test_ac4_valid_fifo_and_fee_controls(tmp_path, monkeypatch, fills, expected):
    rows = [
        _row(side, qty, price, day=i + 1, fee=fee)
        for i, (side, qty, price, fee) in enumerate(fills)
    ]
    result = _analyze(tmp_path, monkeypatch, rows)
    assert result["status"] == "ok"
    assert result["profile"]["total_pnl"] == pytest.approx(expected)


@pytest.mark.parametrize("dividend_only", [False, True])
def test_ac5_dividend_zero_quantity_and_missing_fee(
    tmp_path, monkeypatch, dividend_only
):
    dividend = _row("dividend", 0, 0, day=3, fee=0)
    dividend["amount"] = 5
    rows = [] if dividend_only else [_row(), _row("sell", price=110, day=2)]
    for row in rows:
        row.pop("fee")
    result = _analyze(tmp_path, monkeypatch, rows + [dividend])
    assert result["status"] == "ok"
    assert result["profile"]["total_dividends"] == 5
    assert result["profile"]["total_roundtrips"] == (0 if dividend_only else 1)
    assert result["profile"]["total_pnl"] == (5 if dividend_only else 15)


def test_ac5_skipped_nontrade_row_does_not_require_quantity(tmp_path, monkeypatch):
    rows = [_row(), _row("sell", price=110, day=2), _row("interest", "bad", day=3)]
    result = _analyze(tmp_path, monkeypatch, rows)
    assert result["status"] == "ok"
    assert result["total_records"] == 2
    assert result["profile"]["total_pnl"] == 8
