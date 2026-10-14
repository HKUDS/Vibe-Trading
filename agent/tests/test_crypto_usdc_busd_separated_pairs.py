"""Separator-spelled USDC/BUSD crypto pairs must classify as crypto.

``BTCUSDC`` was already crypto, but ``BTC-USDC`` / ``ETH/USDC`` matched no
pattern and fell through to the ``a_share`` default (T+1, no shorting, CNY,
tushare) even though ``correlation.infer_market`` already called them crypto.
"""

from __future__ import annotations

import pytest

from backtest.correlation import infer_market
from backtest.engines._market_hooks import _detect_market, code_currency
from src.market_data import detect_source


@pytest.mark.parametrize(
    "code",
    ["BTC-USDC", "ETH/USDC", "SOL-USDC", "BTC-BUSD", "ETH/BUSD", "btc-usdc", "BTCUSDC"],
)
def test_separated_usdc_busd_pairs_are_crypto(code: str) -> None:
    assert _detect_market(code.upper()) == "crypto"
    assert code_currency(code.upper()) == "USD"
    assert infer_market(code) == "crypto"


@pytest.mark.parametrize("code", ["BTC-USDC", "ETH/USDC", "BTC-BUSD"])
def test_separated_usdc_busd_pairs_use_the_crypto_source_chain(code: str) -> None:
    assert detect_source(code) == "okx"


@pytest.mark.parametrize(
    ("code", "market"),
    [
        ("USDCAD", "forex"),
        ("USDCHF", "forex"),
        ("EUR/USD", "forex"),
        ("600000", "a_share"),
        ("000001.SZ", "a_share"),
        ("AAPL", "us_equity"),
    ],
)
def test_non_crypto_symbols_keep_their_market(code: str, market: str) -> None:
    assert infer_market(code) == market


@pytest.mark.parametrize("code", ["000001-USDC", "000001/BUSD"])
def test_digit_only_base_is_not_crypto(code: str) -> None:
    assert _detect_market(code) != "crypto"
