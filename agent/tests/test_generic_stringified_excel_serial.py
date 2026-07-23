"""Generic journal datetime cells must normalize Excel serials from dtype=str loads."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from src.tools.trade_journal_parsers import (
    load_dataframe,
    parse_file,
    parse_generic,
    records_to_dataframe,
)


def test_parse_generic_stringified_excel_serial_datetime() -> None:
    df = pd.DataFrame({
        "datetime": ["45321.375", "45322.0"],
        "symbol": ["AAPL", "MSFT"],
        "side": ["buy", "sell"],
        "quantity": ["10", "5"],
        "price": ["150", "200"],
    })
    recs = parse_generic(df)
    assert [r.datetime for r in recs] == [
        "2024-01-30 09:00:00",
        "2024-01-31 00:00:00",
    ]
    out = records_to_dataframe(recs)
    assert out["datetime"].notna().all()


def test_parse_file_generic_csv_excel_serial() -> None:
    path = Path(tempfile.mkdtemp()) / "generic.csv"
    path.write_text(
        "datetime,symbol,side,quantity,price\n"
        "45321.375,AAPL,buy,10,150\n",
        encoding="utf-8",
    )
    loaded = load_dataframe(path)
    assert isinstance(loaded["datetime"].iloc[0], str)
    fmt, recs = parse_file(path)
    assert fmt == "generic"
    assert recs[0].datetime == "2024-01-30 09:00:00"
