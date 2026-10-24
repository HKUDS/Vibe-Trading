"""A lone decimal comma ("12,50") must not be read as 1250."""

from __future__ import annotations

import pytest

from src.tools.trade_journal_parsers import _to_float


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12,50", 12.5),
        ("0,5", 0.5),
        ("€12,50", 12.5),
        ("-12,50", -12.5),
        ("(12,50)", -12.5),
        ("0,1250", 0.125),
    ],
)
def test_lone_decimal_comma(raw: str, expected: float) -> None:
    assert _to_float(raw) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1,234", 1234.0), ("1,234,567", 1234567.0), ("(1,234)", -1234.0), ("$1,000", 1000.0)],
)
def test_three_digit_groups_stay_thousands(raw: str, expected: float) -> None:
    assert _to_float(raw) == pytest.approx(expected)


def test_comma_decimal_prices_reach_fifo_analysis(tmp_path, monkeypatch) -> None:
    import csv
    import json

    from src.tools.trade_journal_tool import analyze_trade_journal

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    path = tmp_path / "comma-decimal-journal.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["datetime", "symbol", "side", "quantity", "price", "fee"])
        writer.writerow(["2026-01-02", "SAP", "buy", "10", "120,50", "1,25"])
        writer.writerow(["2026-01-05", "SAP", "sell", "10", "121,50", "1,25"])
    result = json.loads(analyze_trade_journal(str(path), "full"))
    assert result["status"] == "ok"
    # 10 shares * 1.00 gain - 1.25 - 1.25 fees.
    assert result["profile"]["total_pnl"] == pytest.approx(7.5)
