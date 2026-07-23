"""Eastmoney YYYYMMDD dates from Excel floats must normalize to ISO."""

from __future__ import annotations

import pandas as pd

from src.tools.trade_journal_parsers import parse_eastmoney


def test_parse_eastmoney_float_yyyymmdd_date() -> None:
    df = pd.DataFrame([{
        "成交日期": 20260115.0,
        "成交时间": "09:30:00",
        "股票代码": "600519",
        "股票名称": "茅台",
        "买卖标志": "B",
        "成交数量": "100",
        "成交均价": "100",
        "成交金额": "",
        "佣金": "1",
        "印花税": "0",
    }])
    rec = parse_eastmoney(df)
    assert len(rec) == 1
    assert rec[0].datetime == "2026-01-15 09:30:00"


def test_parse_eastmoney_string_yyyymmdd_still_ok() -> None:
    df = pd.DataFrame([{
        "成交日期": "20260115",
        "成交时间": "09:30:00",
        "股票代码": "600519",
        "股票名称": "茅台",
        "买卖标志": "B",
        "成交数量": "100",
        "成交均价": "100",
        "成交金额": "",
        "佣金": "1",
        "印花税": "0",
    }])
    rec = parse_eastmoney(df)
    assert len(rec) == 1
    assert rec[0].datetime == "2026-01-15 09:30:00"
