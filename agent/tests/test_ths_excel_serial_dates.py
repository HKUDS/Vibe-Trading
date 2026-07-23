"""Tonghuashun 成交时间 Excel serial floats must normalize to ISO datetime."""

from __future__ import annotations

import pandas as pd

from src.tools.trade_journal_parsers import parse_tonghuashun


def test_parse_tonghuashun_excel_serial_datetime() -> None:
    # Excel serial 45321.375 = 2024-01-30 09:00:00
    df = pd.DataFrame([{
        "成交时间": 45321.375,
        "证券代码": "600519",
        "证券名称": "茅台",
        "操作": "买入",
        "成交数量": "100",
        "成交价格": "100",
        "成交金额": "10000",
        "手续费": "1",
        "印花税": "0",
        "过户费": "0",
    }])
    rec = parse_tonghuashun(df)
    assert len(rec) == 1
    assert rec[0].datetime == "2024-01-30 09:00:00"


def test_parse_tonghuashun_excel_serial_int64_datetime() -> None:
    """iterrows yields np.int64 for int64 columns; must not treat as ns-epoch."""
    df = pd.DataFrame({
        "成交时间": pd.Series([45321], dtype="int64"),
        "证券代码": ["600519"],
        "证券名称": ["茅台"],
        "操作": ["买入"],
        "成交数量": ["100"],
        "成交价格": ["100"],
        "成交金额": ["10000"],
        "手续费": ["1"],
        "印花税": ["0"],
        "过户费": ["0"],
    })
    rec = parse_tonghuashun(df)
    assert len(rec) == 1
    assert rec[0].datetime == "2024-01-30 00:00:00"


def test_parse_tonghuashun_string_datetime_still_ok() -> None:
    df = pd.DataFrame([{
        "成交时间": "2024-01-01 10:00:00",
        "证券代码": "600519",
        "证券名称": "茅台",
        "操作": "买入",
        "成交数量": "100",
        "成交价格": "100",
        "成交金额": "10000",
        "手续费": "1",
        "印花税": "0",
        "过户费": "0",
    }])
    rec = parse_tonghuashun(df)
    assert len(rec) == 1
    assert rec[0].datetime == "2024-01-01 10:00:00"
