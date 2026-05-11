"""Tests for VNDirect (VND Securities) journal parser."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.tools.journal_parsers_vn.vndirect import VNDirectParser
from src.tools.journal_parsers_vn import detect_vn_format
from src.tools.trade_journal_parsers import (
    TradeRecord,
    detect_format,
    parse_file,
    load_dataframe,
)

FIXTURE = Path(__file__).parent / "fixtures" / "journal_vndirect.csv"


@pytest.fixture
def df():
    return load_dataframe(FIXTURE)


@pytest.fixture
def parser():
    return VNDirectParser()


# -- Detection --

def test_vndirect_detect_positive(df, parser):
    assert parser.detect(df) is True


def test_vndirect_detect_via_registry(df):
    assert detect_vn_format(df) == "vndirect"


def test_vndirect_detect_via_top_level(df):
    assert detect_format(df) == "vndirect"


def test_vndirect_detect_empty_df(parser):
    assert parser.detect(pd.DataFrame()) is False


def test_vndirect_detect_negative_ssi(parser):
    """SSI-shape df has 'Mã CK' instead of 'Mã' — must NOT match."""
    fake = pd.DataFrame([{
        "Ngày GD": "15/03/2024",
        "Mã CK": "VNM",
        "Loại GD": "Mua",
        "KL khớp": 500,
        "Giá khớp": 68500,
    }])
    assert parser.detect(fake) is False


def test_vndirect_detect_negative_hsc(parser):
    """HSC-shape df has English 'Symbol'/'Trade Date' — must NOT match."""
    fake = pd.DataFrame([{
        "Trade Date": "2024-03-15",
        "Symbol": "VNM",
        "Side": "Buy",
        "Quantity": 500,
        "Price": 68500,
    }])
    assert parser.detect(fake) is False


def test_vndirect_detect_negative_tonghuashun(parser):
    fake = pd.DataFrame([{"成交日期": "20240315", "证券代码": "600519", "买卖标志": "买入"}])
    assert parser.detect(fake) is False


# -- Parsing --

def test_vndirect_parse_count(df, parser):
    records = parser.parse(df)
    assert len(records) == 6  # 7 rows - 1 skipped (empty symbol + qty=0)


def test_vndirect_parse_returns_traderecord(df, parser):
    records = parser.parse(df)
    assert all(isinstance(r, TradeRecord) for r in records)


def test_vndirect_parse_first_buy(df, parser):
    records = parser.parse(df)
    r = records[0]
    assert r.symbol == "MWG.HOSE"
    assert r.side == "buy"
    assert r.quantity == 200.0
    assert r.price == 52500.0
    assert r.market == "vn_equity"
    assert r.datetime == "2024-04-05"


def test_vndirect_parse_qualifies_dgc_to_hnx(df, parser):
    """DGC is in _KNOWN_HNX_TICKERS — must qualify to .HNX."""
    records = parser.parse(df)
    dgc = next(r for r in records if r.symbol == "DGC.HNX")
    assert dgc is not None


def test_vndirect_parse_qualifies_vre_to_hose(df, parser):
    records = parser.parse(df)
    vre = next(r for r in records if r.symbol == "VRE.HOSE")
    assert vre is not None


def test_vndirect_parse_sell_combines_tax_and_fee(df, parser):
    records = parser.parse(df)
    sell = next(r for r in records if r.side == "sell" and r.symbol == "MWG.HOSE")
    # fee 16140 + tax 10760 = 26900
    assert sell.fee == pytest.approx(26900.0)


# -- End-to-end via parse_file --

def test_vndirect_parse_file():
    fmt, records = parse_file(FIXTURE)
    assert fmt == "vndirect"
    assert len(records) == 6
    assert all(r.market == "vn_equity" for r in records)
