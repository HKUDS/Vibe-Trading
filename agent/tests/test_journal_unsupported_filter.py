"""A journal filter that cannot be applied must fail, not be reported as applied."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.tools.trade_journal_tool import _apply_filter, analyze_trade_journal


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-01-15", "2026-02-15"]),
            "symbol": ["AAPL", "MSFT"],
            "market": ["us", "us"],
        }
    )


@pytest.mark.parametrize("expr", ["ticker=AAPL", "code=AAPL", "2026-01", "AAPL"])
def test_unsupported_filters_raise(expr: str) -> None:
    with pytest.raises(ValueError, match="unsupported filter"):
        _apply_filter(_frame(), expr)


@pytest.mark.parametrize(
    "expr, symbols",
    [("symbol=aapl", ["AAPL"]), ("market=us", ["AAPL", "MSFT"]), ("", ["AAPL", "MSFT"]),
     ("2026-02 to 2026-02", ["MSFT"])],
)
def test_supported_filters_still_apply(expr: str, symbols: list[str]) -> None:
    assert list(_apply_filter(_frame(), expr)["symbol"]) == symbols


def test_tool_reports_an_unsupported_filter_as_an_error(tmp_path, monkeypatch) -> None:
    path = tmp_path / "journal.csv"
    path.write_text(
        "datetime,symbol,side,quantity,price,fee\n"
        "2026-01-02,AAPL,buy,10,100,1\n2026-01-05,AAPL,sell,10,110,1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    payload = json.loads(analyze_trade_journal(str(path), "profile", "ticker=AAPL"))
    assert payload["status"] == "error"
    assert "unsupported filter" in payload["error"]
