"""Tests for SSI iBoard journal parser."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.tools.journal_parsers_vn.ssi import SSIParser
from src.tools.journal_parsers_vn import detect_vn_format
from src.tools.trade_journal_parsers import (
    TradeRecord,
    detect_format,
    parse_file,
    load_dataframe,
)

FIXTURE = Path(__file__).parent / "fixtures" / "journal_ssi.csv"


@pytest.fixture
def df():
    return load_dataframe(FIXTURE)


@pytest.fixture
def parser():
    return SSIParser()


# -- Detection --

def test_ssi_detect_positive(df, parser):
    assert parser.detect(df) is True


def test_ssi_detect_via_registry(df):
    assert detect_vn_format(df) == "ssi"


def test_ssi_detect_via_top_level(df):
    # Top-level detect_format should also return "ssi"
    assert detect_format(df) == "ssi"


def test_ssi_detect_negative_tonghuashun(parser):
    fake = pd.DataFrame([{"成交日期": "20240315", "证券代码": "600519", "买卖标志": "买入"}])
    assert parser.detect(fake) is False


def test_ssi_detect_empty_df(parser):
    assert parser.detect(pd.DataFrame()) is False


# -- Parsing --

def test_ssi_parse_count(df, parser):
    records = parser.parse(df)
    assert len(records) == 6  # 7 rows - 1 skipped (empty symbol + qty=0)


def test_ssi_parse_returns_traderecord(df, parser):
    records = parser.parse(df)
    assert all(isinstance(r, TradeRecord) for r in records)


def test_ssi_parse_first_buy(df, parser):
    records = parser.parse(df)
    r = records[0]
    assert r.symbol == "VNM.HOSE"
    assert r.side == "buy"
    assert r.quantity == 500.0
    assert r.price == 68500.0
    assert r.market == "vn_equity"
    assert r.datetime == "2024-03-15"


def test_ssi_parse_sell_combines_tax_and_fee(df, parser):
    records = parser.parse(df)
    sell = next(r for r in records if r.side == "sell" and r.symbol == "VNM.HOSE")
    # fee = 51900 + tax 34600 = 86500
    assert sell.fee == pytest.approx(86500.0)


def test_ssi_parse_qualifies_hnx_ticker(df, parser):
    records = parser.parse(df)
    shb = next(r for r in records if r.symbol == "SHB.HNX")
    assert shb is not None


# -- End-to-end via parse_file --

def test_ssi_parse_file(tmp_path):
    fmt, records = parse_file(FIXTURE)
    assert fmt == "ssi"
    assert len(records) == 6
    assert all(r.market == "vn_equity" for r in records)
