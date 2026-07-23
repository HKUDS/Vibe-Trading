"""Futu Date/Time Excel serial floats must normalize to ISO datetime."""

from __future__ import annotations

import pandas as pd

from src.tools.trade_journal_parsers import parse_futu


def test_parse_futu_excel_serial_date_and_time() -> None:
    # Excel serial 45321.0 + 0.375 day = 2024-01-30 09:00:00
    df = pd.DataFrame([{
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
    }])
    rec = parse_futu(df)
    assert len(rec) == 1
    assert rec[0].datetime == "2024-01-30 09:00:00"


def test_parse_futu_excel_serial_int64_date() -> None:
    """iterrows yields np.int64 for int64 columns; must not treat as ns-epoch."""
    df = pd.DataFrame({
        "Date": pd.Series([45321], dtype="int64"),
        "Time": ["09:00:00"],
        "Symbol": ["AAPL"],
        "Name": ["Apple"],
        "Side": ["Buy"],
        "Quantity": [10],
        "Price": [100],
        "Amount": [1000],
        "Commission": [1],
        "Platform Fee": [0],
    })
    rec = parse_futu(df)
    assert len(rec) == 1
    assert rec[0].datetime == "2024-01-30 09:00:00"


def test_parse_futu_string_date_time_still_ok() -> None:
    df = pd.DataFrame([{
        "Date": "2024-02-04",
        "Time": "09:00:00",
        "Symbol": "AAPL",
        "Name": "Apple",
        "Side": "Buy",
        "Quantity": 10,
        "Price": 100,
        "Amount": 1000,
        "Commission": 1,
        "Platform Fee": 0,
    }])
    rec = parse_futu(df)
    assert len(rec) == 1
    assert rec[0].datetime == "2024-02-04 09:00:00"
