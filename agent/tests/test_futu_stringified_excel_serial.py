"""Futu Excel serial dates must survive load_dataframe dtype=str."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from src.tools.trade_journal_parsers import load_dataframe, parse_file, parse_futu


def test_parse_futu_stringified_excel_serial_date_and_time() -> None:
    df = pd.DataFrame([{
        "Date": "45321.0",
        "Time": "0.375",
        "Symbol": "AAPL",
        "Name": "Apple",
        "Side": "Buy",
        "Quantity": "10",
        "Price": "100",
        "Amount": "1000",
        "Commission": "1",
        "Platform Fee": "0",
    }])
    rec = parse_futu(df)
    assert len(rec) == 1
    assert rec[0].datetime == "2024-01-30 09:00:00"


def test_parse_file_xlsx_stringified_excel_serial() -> None:
    path = Path(tempfile.mkdtemp()) / "futu.xlsx"
    pd.DataFrame([{
        "Date": 45321.0,
        "Time": 0.375,
        "Symbol": "AAPL",
        "Name": "Apple",
        "Side": "Buy",
        "Quantity": 10,
        "Price": 100,
        "Amount": 1000,
        "Commission": 1,
        "Platform Fee": 0,
    }]).to_excel(path, index=False)
    loaded = load_dataframe(path)
    assert isinstance(loaded["Date"].iloc[0], str)
    fmt, recs = parse_file(path)
    assert fmt == "futu"
    assert recs[0].datetime == "2024-01-30 09:00:00"
