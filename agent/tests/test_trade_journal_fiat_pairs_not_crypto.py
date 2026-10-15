"""A fiat/fiat currency pair in a trade journal must not be labelled crypto."""

from __future__ import annotations

import pytest

import pandas as pd

from src.tools.trade_journal_parsers import _infer_market_from_symbol, parse_generic


@pytest.mark.parametrize(
    "symbol",
    ["EUR/USD", "GBP/USD", "USD/JPY", "usd-cnh", "AUD-USD", "USD/CHF"],
)
def test_fiat_cross_is_not_crypto(symbol: str) -> None:
    assert _infer_market_from_symbol(symbol) == "other"


@pytest.mark.parametrize(
    "symbol",
    ["BTC-USD", "BTC/USD", "ETH/BTC", "ETH-USDT", "SOL/USDC", "BTC-EUR", "ETH-USD"],
)
def test_crypto_pairs_stay_crypto(symbol: str) -> None:
    assert _infer_market_from_symbol(symbol) == "crypto"


def test_generic_journal_row_for_a_currency_cross_gets_other_market() -> None:
    df = pd.DataFrame(
        {
            "datetime": ["2026-01-02 10:00:00"],
            "symbol": ["EUR/USD"],
            "side": ["buy"],
            "quantity": ["1000"],
            "price": ["1.10"],
        }
    )
    (record,) = parse_generic(df)
    assert record.market == "other"
