"""Tests for DNSE (LightSpeed) broker journal parser."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.tools.journal_parsers_vn import detect_vn_format
from src.tools.journal_parsers_vn.dnse import DNSEParser
from src.tools.trade_journal_parsers import (
    TradeRecord,
    detect_format,
    load_dataframe,
    parse_file,
)

FIXTURE = Path(__file__).parent / "fixtures" / "journal_dnse.csv"


@pytest.fixture
def df():
    return load_dataframe(FIXTURE)


@pytest.fixture
def parser():
    return DNSEParser()


# ── Detection ──

def test_dnse_detect_positive(df, parser):
    assert parser.detect(df) is True


def test_dnse_detect_via_registry(df):
    assert detect_vn_format(df) == "dnse"


def test_dnse_detect_via_top_level(df):
    assert detect_format(df) == "dnse"


def test_dnse_detect_negative_hsc(parser):
    fake = pd.DataFrame([{
        "Trade Date": "2024-01-01",
        "Symbol": "VNM",
        "Side": "BUY",
        "Quantity": 100,
        "Matched Price": 68000,
        "Net Amount": 6800000,
    }])
    assert parser.detect(fake) is False


def test_dnse_detect_negative_ssi(parser):
    fake = pd.DataFrame([{
        "Trade Date": "2024-01-01",
        "Symbol": "VNM",
        "Side": "BUY",
        "Match Volume": 100,
        "Match Price": 68000,
    }])
    assert parser.detect(fake) is False


def test_dnse_detect_negative_vndirect(parser):
    fake = pd.DataFrame([{
        "Ngày": "01/01/2024",
        "Mã": "VNM",
        "Loại lệnh": "Mua",
        "Khối lượng": 100,
        "Giá": 68000,
    }])
    assert parser.detect(fake) is False


def test_dnse_detect_empty(parser):
    assert parser.detect(pd.DataFrame()) is False


# ── Parsing ──

def test_dnse_parse_count(df, parser):
    records = parser.parse(df)
    assert len(records) == 6


def test_dnse_parse_returns_traderecord(df, parser):
    records = parser.parse(df)
    assert all(isinstance(r, TradeRecord) for r in records)


def test_dnse_parse_first_buy(df, parser):
    records = parser.parse(df)
    r = records[0]
    assert r.symbol == "MSN.HOSE"
    assert r.side == "buy"
    assert r.quantity == 500.0
    assert r.price == 77500.0
    assert r.datetime == "2024-06-03"
    assert r.market == "vn_equity"


def test_dnse_parse_no_tax_column(df, parser):
    """Fixture deliberately omits Tax column — fee field must equal Fee column only."""
    records = parser.parse(df)
    first_buy = records[0]
    # Row 1: MSN buy, Fee=58125, no Tax column → fee should be 58125 exactly
    assert first_buy.fee == pytest.approx(58125.0)


def test_dnse_parse_qualifies_hose_tickers(df, parser):
    records = parser.parse(df)
    syms = {r.symbol for r in records}
    assert "MSN.HOSE" in syms
    assert "VPB.HOSE" in syms
    assert "VIC.HOSE" in syms


# ── End-to-end ──

def test_dnse_parse_file():
    fmt, records = parse_file(FIXTURE)
    assert fmt == "dnse"
    assert len(records) == 6
    assert all(r.market == "vn_equity" for r in records)
