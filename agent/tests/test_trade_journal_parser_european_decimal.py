"""European "1.234,56" cells must not be read as 1.23456."""

from __future__ import annotations

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


import pytest

from src.tools.trade_journal_parsers import _to_float


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,56", 1234.56),
        ("1.234.567,5", 1234567.5),
        ("€1.234,56", 1234.56),
        ("-1.234,56", -1234.56),
        ("(1.234,56)", -1234.56),
        ("12.345,6 EUR", 12345.6),
    ],
)
def test_comma_decimal_with_dot_grouping(raw: str, expected: float) -> None:
    assert _to_float(raw) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1,234.56", 1234.56), ("1,234,567.89", 1234567.89), ("1,234", 1234.0), ("12.5", 12.5), ("$1,000", 1000.0)],
)
def test_us_formats_are_unchanged(raw: str, expected: float) -> None:
    assert _to_float(raw) == pytest.approx(expected)


def test_european_amounts_reach_fifo_analysis(tmp_path, monkeypatch) -> None:
    import csv
    import json

    from src.tools.trade_journal_tool import analyze_trade_journal

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    path = tmp_path / "european-journal.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["datetime", "symbol", "side", "quantity", "price", "fee"])
        writer.writerow(["2026-01-02", "AAPL", "buy", "1.000,00", "1.234,50", "1.000,25"])
        writer.writerow(["2026-01-05", "AAPL", "sell", "1.000,00", "1.235,50", "1.000,75"])
    result = json.loads(analyze_trade_journal(str(path), "full", roots=FileRoots.from_config(get_env_config().api)))
    assert result["status"] == "ok"
    # 1,000 shares * 1.00 price gain - 1,000.25 entry fee - 1,000.75 exit fee.
    assert result["profile"]["total_pnl"] == -1001.0
