"""Crypto bases that start with a digit (1INCH, 1000PEPE) must stay crypto.

The USDT-pair patterns used ``[A-Z]+`` for the base asset, so ``1INCH-USDT``
matched nothing and fell through to the ``a_share`` default: T+1 settlement,
no shorting, CNY and the tushare source were applied to a crypto pair.
Digit-only codes are equities (A-share / HK) and must be unaffected.
"""

from __future__ import annotations

import pytest

from backtest.correlation import _normalize_symbol, infer_market
from backtest.engines._market_hooks import _detect_market
from backtest.engines.base import _CRYPTO_RE
from src.market_data import detect_source, normalize_crypto_symbol

DIGIT_LEADING_PAIRS = [
    "1INCH-USDT",
    "1INCH/USDT",
    "1INCHUSDT",
    "1000PEPE-USDT",
    "1000PEPE/USDT",
    "1000SHIBUSDT",
    "1inch-usdt",
]


@pytest.mark.parametrize("code", DIGIT_LEADING_PAIRS)
def test_digit_leading_base_is_classified_as_crypto(code: str) -> None:
    assert _detect_market(code.upper()) == "crypto"
    assert infer_market(code) == "crypto"


@pytest.mark.parametrize("code", ["1INCH-USDT", "1INCH/USDT", "1000PEPE-USDT", "1000PEPE/USDT"])
def test_signal_alignment_regex_accepts_digit_leading_base(code: str) -> None:
    assert _CRYPTO_RE.match(code)


@pytest.mark.parametrize(
    ("code", "source"),
    [("1INCH-USDT", "okx"), ("1000PEPE-USDT", "okx"), ("1INCH/USDT", "ccxt")],
)
def test_digit_leading_base_selects_crypto_source(code: str, source: str) -> None:
    assert detect_source(code) == source


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("1INCH/USDT", "1INCH-USDT"),
        ("1inch-usdt", "1INCH-USDT"),
        ("1INCHUSDT", "1INCH-USDT"),
        ("1000SHIBUSDT", "1000SHIB-USDT"),
        ("BTCUSDT", "BTC-USDT"),
    ],
)
def test_digit_leading_base_normalizes_to_dash_pair(code: str, expected: str) -> None:
    assert normalize_crypto_symbol(code) == expected
    assert _normalize_symbol(code, "crypto") == expected


@pytest.mark.parametrize(
    ("code", "market"),
    [
        ("000001.SZ", "a_share"),
        ("600000", "a_share"),
        ("600000.SH", "a_share"),
        ("0700.HK", "hk_equity"),
        ("00700", "hk_equity"),
    ],
)
def test_digit_only_equity_codes_are_not_captured(code: str, market: str) -> None:
    assert infer_market(code) == market
    assert not _CRYPTO_RE.match(code)


@pytest.mark.parametrize("code", ["600000USDT", "000001-USDT", "000001/USDT", "000001-USD"])
def test_digit_only_base_is_never_crypto(code: str) -> None:
    assert _detect_market(code) != "crypto"
    assert not _CRYPTO_RE.match(code)
    assert normalize_crypto_symbol(code) == code
