"""Tonghuashun Excel serials must survive load_dataframe dtype=str."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from src.tools.trade_journal_parsers import load_dataframe, parse_file, parse_tonghuashun


def test_parse_tonghuashun_stringified_excel_serial() -> None:
    df = pd.DataFrame([{
        "成交时间": "45321.375",
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


def test_parse_file_xlsx_stringified_excel_serial() -> None:
    path = Path(tempfile.mkdtemp()) / "ths.xlsx"
    pd.DataFrame([{
        "成交时间": 45321.375,
        "证券代码": "600519",
        "证券名称": "茅台",
        "操作": "买入",
        "成交数量": 100,
        "成交价格": 100,
        "成交金额": 10000,
        "手续费": 1,
        "印花税": 0,
        "过户费": 0,
    }]).to_excel(path, index=False)
    loaded = load_dataframe(path)
    assert isinstance(loaded["成交时间"].iloc[0], str)
    fmt, recs = parse_file(path)
    assert fmt == "tonghuashun"
    assert recs[0].datetime == "2024-01-30 09:00:00"
