"""Suffixed US tickers and Yahoo's Shanghai alias get their journal market."""

from __future__ import annotations

import pandas as pd
import pytest

from src.tools.trade_journal_parsers import _infer_market_from_symbol, parse_generic


@pytest.mark.parametrize(
    "symbol, market",
    [
        ("AAPL.US", "us"),
        ("aapl.us", "us"),
        ("BF-B.US", "us"),
        ("BRK.B.US", "us"),
        ("600519.SS", "china_a"),
        ("AAPL", "us"),
        ("600519.SH", "china_a"),
        ("BTC-USD", "crypto"),
        ("EUR/USD", "other"),
    ],
)
def test_suffixed_symbols_map_to_their_market(symbol: str, market: str) -> None:
    assert _infer_market_from_symbol(symbol) == market


def test_generic_journal_rows_with_us_suffix_are_us_market() -> None:
    df = pd.DataFrame(
        {
            "datetime": ["2026-01-02", "2026-01-05"],
            "symbol": ["AAPL.US", "AAPL.US"],
            "side": ["buy", "sell"],
            "quantity": [10, 10],
            "price": [100, 110],
        }
    )
    assert [record.market for record in parse_generic(df)] == ["us", "us"]
