"""Tests for TCBS (Techcom Securities) broker journal parser."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.tools.journal_parsers_vn import detect_vn_format
from src.tools.journal_parsers_vn.tcbs import TCBSParser
from src.tools.trade_journal_parsers import (
    TradeRecord,
    detect_format,
    load_dataframe,
    parse_file,
)

FIXTURE = Path(__file__).parent / "fixtures" / "journal_tcbs.csv"


@pytest.fixture
def df():
    return load_dataframe(FIXTURE)


@pytest.fixture
def parser():
    return TCBSParser()


# ── Detection ──

def test_tcbs_detect_positive(df, parser):
    assert parser.detect(df) is True


def test_tcbs_detect_via_registry(df):
    assert detect_vn_format(df) == "tcbs"


def test_tcbs_detect_via_top_level(df):
    assert detect_format(df) == "tcbs"


def test_tcbs_detect_negative_ssi(parser):
    fake = pd.DataFrame([{
        "Ngày GD": "01/01/2024",
        "Mã CK": "VNM",
        "Loại GD": "Mua",
        "KL khớp": 100,
        "Giá khớp": 68000,
    }])
    assert parser.detect(fake) is False


def test_tcbs_detect_negative_vndirect(parser):
    fake = pd.DataFrame([{
        "Ngày": "01/01/2024",
        "Mã": "VNM",
        "Loại lệnh": "Mua",
        "Khối lượng": 100,
        "Giá": 68000,
    }])
    assert parser.detect(fake) is False


def test_tcbs_detect_negative_hsc(parser):
    fake = pd.DataFrame([{
        "Trade Date": "2024-01-01",
        "Symbol": "VNM",
        "Side": "BUY",
        "Quantity": 100,
        "Matched Price": 68000,
    }])
    assert parser.detect(fake) is False


def test_tcbs_detect_empty(parser):
    assert parser.detect(pd.DataFrame()) is False


# ── Parsing ──

def test_tcbs_parse_count(df, parser):
    records = parser.parse(df)
    assert len(records) == 6


def test_tcbs_parse_returns_traderecord(df, parser):
    records = parser.parse(df)
    assert all(isinstance(r, TradeRecord) for r in records)


def test_tcbs_parse_first_buy(df, parser):
    records = parser.parse(df)
    r = records[0]
    assert r.symbol == "VCB.HOSE"
    assert r.side == "buy"
    assert r.quantity == 200.0
    assert r.price == 92000.0
    assert r.datetime == "2024-05-02"
    assert r.market == "vn_equity"


def test_tcbs_parse_sell_combines_tax_and_fee(df, parser):
    records = parser.parse(df)
    sell = next(r for r in records if r.side == "sell" and r.symbol == "VCB.HOSE")
    # fee = 28050 + tax 18700 = 46750
    assert sell.fee == pytest.approx(46750.0)


def test_tcbs_parse_qualifies_hose_tickers(df, parser):
    records = parser.parse(df)
    syms = {r.symbol for r in records}
    assert "VCB.HOSE" in syms
    assert "TCB.HOSE" in syms
    assert "GAS.HOSE" in syms


# ── End-to-end ──

def test_tcbs_parse_file():
    fmt, records = parse_file(FIXTURE)
    assert fmt == "tcbs"
    assert len(records) == 6
    assert all(r.market == "vn_equity" for r in records)
