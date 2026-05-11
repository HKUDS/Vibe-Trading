"""Tests for HSC (Ho Chi Minh Securities) broker journal parser."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.tools.journal_parsers_vn import detect_vn_format, VN_PARSER_REGISTRY
from src.tools.journal_parsers_vn.hsc import HSCParser
from src.tools.trade_journal_parsers import (
    TradeRecord,
    detect_format,
    load_dataframe,
    parse_file,
)


FIXTURE = Path(__file__).parent / "fixtures" / "journal_hsc.csv"


@pytest.fixture
def hsc_df() -> pd.DataFrame:
    return load_dataframe(FIXTURE)


@pytest.fixture
def parser() -> HSCParser:
    return HSCParser()


# ---------------- Detection ----------------

def test_detect_positive(parser: HSCParser, hsc_df: pd.DataFrame) -> None:
    assert parser.detect(hsc_df) is True


def test_detect_via_registry(hsc_df: pd.DataFrame) -> None:
    # Force registry initialization, then test dispatcher
    assert "hsc" in VN_PARSER_REGISTRY or detect_vn_format(hsc_df) is not None
    assert detect_vn_format(hsc_df) == "hsc"


def test_detect_via_top_level(hsc_df: pd.DataFrame) -> None:
    assert detect_format(hsc_df) == "hsc"


def test_detect_negative_tonghuashun(parser: HSCParser) -> None:
    fake = pd.DataFrame([{
        "成交时间": "2024-01-01 10:00:00",
        "证券代码": "600519",
        "操作": "买入",
        "成交数量": 100,
        "成交均价": 1700.0,
    }])
    assert parser.detect(fake) is False


def test_detect_negative_ssi(parser: HSCParser) -> None:
    fake_ssi = pd.DataFrame([{
        "Trade Date": "2024-01-01",
        "Symbol": "VNM",
        "Side": "BUY",
        "Match Volume": 100,
        "Match Price": 68000,
    }])
    assert parser.detect(fake_ssi) is False


def test_detect_empty(parser: HSCParser) -> None:
    assert parser.detect(pd.DataFrame()) is False


# ---------------- Parsing ----------------

def test_parse_count(parser: HSCParser, hsc_df: pd.DataFrame) -> None:
    records = parser.parse(hsc_df)
    assert len(records) == 5  # row 6 (empty symbol / qty=0) is skipped


def test_parse_returns_traderecord(parser: HSCParser, hsc_df: pd.DataFrame) -> None:
    records = parser.parse(hsc_df)
    assert all(isinstance(r, TradeRecord) for r in records)


def test_parse_first_buy(parser: HSCParser, hsc_df: pd.DataFrame) -> None:
    records = parser.parse(hsc_df)
    first = records[0]
    assert first.symbol == "HPG.HOSE"
    assert first.side == "buy"
    assert first.quantity == 1000
    assert first.price == 28500
    assert first.market == "vn_equity"


def test_parse_sell_combines_tax_fee(parser: HSCParser, hsc_df: pd.DataFrame) -> None:
    records = parser.parse(hsc_df)
    # First HPG SELL row: fee=22350 + tax=14900 = 37250
    sells = [r for r in records if r.symbol == "HPG.HOSE" and r.side == "sell"]
    assert len(sells) == 2
    first_sell = sells[0]
    assert first_sell.fee == 22350 + 14900


def test_parse_qualifies_symbols(parser: HSCParser, hsc_df: pd.DataFrame) -> None:
    records = parser.parse(hsc_df)
    syms = {r.symbol for r in records}
    assert "HPG.HOSE" in syms
    assert "MWG.HOSE" in syms
    assert "VHM.HOSE" in syms


def test_parse_file_end_to_end() -> None:
    fmt, records = parse_file(FIXTURE)
    assert fmt == "hsc"
    assert len(records) == 5
    assert all(isinstance(r, TradeRecord) for r in records)
