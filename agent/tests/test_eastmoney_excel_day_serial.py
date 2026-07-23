"""Eastmoney Excel day-count serials must normalize to ISO dates."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from src.tools.trade_journal_parsers import load_dataframe, parse_eastmoney, parse_file


def test_parse_eastmoney_stringified_excel_day_serial() -> None:
    # 2023-01-15 as an Excel day-count serial (not YYYYMMDD).
    df = pd.DataFrame([{
        "成交日期": "44941.0",
        "成交时间": "09:35:00",
        "股票代码": "600519",
        "股票名称": "贵州茅台",
        "买卖标志": "B",
        "成交数量": "100",
        "成交均价": "1800",
        "成交金额": "180000",
        "佣金": "5",
        "印花税": "0",
    }])
    rec = parse_eastmoney(df)
    assert len(rec) == 1
    assert rec[0].datetime == "2023-01-15 09:35:00"


def test_parse_eastmoney_numeric_excel_day_serial() -> None:
    df = pd.DataFrame([{
        "成交日期": 44941.0,
        "成交时间": "09:35:00",
        "股票代码": "600519",
        "股票名称": "贵州茅台",
        "买卖标志": "B",
        "成交数量": 100,
        "成交均价": 1800,
        "成交金额": 180000,
        "佣金": 5,
        "印花税": 0,
    }])
    rec = parse_eastmoney(df)
    assert len(rec) == 1
    assert rec[0].datetime == "2023-01-15 09:35:00"


def test_parse_eastmoney_yyyymmdd_float_still_ok() -> None:
    df = pd.DataFrame([{
        "成交日期": "20230115.0",
        "成交时间": "09:35:00",
        "股票代码": "600519",
        "股票名称": "贵州茅台",
        "买卖标志": "B",
        "成交数量": "100",
        "成交均价": "1800",
        "成交金额": "180000",
        "佣金": "5",
        "印花税": "0",
    }])
    rec = parse_eastmoney(df)
    assert len(rec) == 1
    assert rec[0].datetime == "2023-01-15 09:35:00"


def test_parse_file_xlsx_eastmoney_excel_day_serial() -> None:
    path = Path(tempfile.mkdtemp()) / "em.xlsx"
    pd.DataFrame([{
        "成交日期": 44941.0,
        "成交时间": "09:35:00",
        "股票代码": "600519",
        "股票名称": "贵州茅台",
        "买卖标志": "B",
        "成交数量": 100,
        "成交均价": 1800,
        "成交金额": 180000,
        "佣金": 5,
        "印花税": 0,
    }]).to_excel(path, index=False)
    loaded = load_dataframe(path)
    assert isinstance(loaded["成交日期"].iloc[0], str)
    fmt, recs = parse_file(path)
    assert fmt == "eastmoney"
    assert recs[0].datetime == "2023-01-15 09:35:00"
