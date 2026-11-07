"""Every market the data layer routes is known to identity and symbol search (#1565).

A market is added in ``backtest.engines._market_hooks`` (pattern + currency) and
the backtest can then price it. The grounding identity layer and symbol search
keep their own suffix tables, and nothing tied them to that one: ``.L``, ``.VN``
and ``.BA`` each shipped with no canonical-symbol scan, no venue, no currency,
and search results labelled ``global``. This test makes the backtest's currency
table the list, so a new market fails here until it has a row.
"""

from __future__ import annotations

import pytest

from backtest.engines._market_hooks import _MARKET_CURRENCY, _detect_market
from src.agent.grounding.identity import _infer_currency, _infer_venue, _scan_symbols
from src.tools.symbol_search_tool import _from_yahoo_symbol

# market -> (project symbol, Yahoo's spelling of it, symbol-search label)
_SAMPLES: dict[str, tuple[str, str, str]] = {
    "a_share": ("600519.SH", "600519.SS", "cn"),
    "us_equity": ("AAPL.US", "AAPL", "us"),
    "hk_equity": ("00700.HK", "0700.HK", "hk"),
    "india_equity": ("RELIANCE.NS", "RELIANCE.NS", "in"),
    "kr_equity": ("005930.KS", "005930.KS", "kr"),
    "ca_equity": ("TD.TO", "TD.TO", "ca"),
    "ar_equity": ("GGAL.BA", "GGAL.BA", "ar"),
    "br_equity": ("PETR4.SA", "PETR4.SA", "br"),
    "uk_equity": ("VOD.L", "VOD.L", "uk"),
    "vietnam_equity": ("VIC.VN", "VIC.VN", "vn"),
    "taiwan_equity": ("2330.TW", "2330.TW", "tw"),
}

# Crypto has a currency row but no listing suffix: its pairs carry the quote.
_NOT_A_LISTING_MARKET = {"crypto"}


def test_every_currency_market_has_a_sample() -> None:
    assert set(_SAMPLES) == set(_MARKET_CURRENCY) - _NOT_A_LISTING_MARKET


@pytest.mark.parametrize("market", sorted(_SAMPLES))
def test_identity_and_search_know_the_market(market: str) -> None:
    symbol, yahoo_symbol, label = _SAMPLES[market]

    assert _detect_market(symbol) == market
    assert _scan_symbols(f"What did {symbol} close at yesterday?") == {symbol}
    assert _infer_venue(symbol) is not None
    assert _infer_currency(symbol) == _MARKET_CURRENCY[market]
    assert _from_yahoo_symbol(yahoo_symbol, {"quoteType": "EQUITY"}) == (symbol, label)


# Taiwan codes are numeric, and ETFs can end in a letter (00400A.TW), so the
# letter-first suffix branch cannot see them. TPEx (.TWO) is the second venue,
# and .TWO must not scan as a .TW match with a stray "O".
@pytest.mark.parametrize(
    ("symbol", "venue"),
    [("2330.TW", "twse"), ("6488.TWO", "tpex"), ("00400A.TW", "twse")],
)
def test_taiwan_spellings_each_scan_as_one_symbol(symbol: str, venue: str) -> None:
    assert _detect_market(symbol) == "taiwan_equity"
    assert _scan_symbols(f"How did {symbol} trade today?") == {symbol}
    assert _infer_venue(symbol) == venue
    assert _infer_currency(symbol) == "TWD"
    assert _from_yahoo_symbol(symbol, {"quoteType": "EQUITY"}) == (symbol, "tw")
