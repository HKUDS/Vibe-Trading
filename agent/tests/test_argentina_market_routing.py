"""Regression tests for Yahoo-backed Argentina (.BA) market routing.

These tests are deterministic and do not make network requests.  They pin the
routing contract separately from Yahoo data availability.
"""

from __future__ import annotations

import pytest

from backtest.engines._market_hooks import _detect_market, code_currency
from backtest.loaders.registry import FALLBACK_CHAINS
from backtest.loaders.yahoo_loader import _is_supported as yahoo_is_supported
from backtest.loaders.yfinance_loader import _to_yfinance_symbol
from backtest.runner import _create_market_engine, _detect_source
from src.market_data import detect_source
from src.tools.stock_profile_tool import _market_for


@pytest.mark.parametrize("symbol", ["GGAL.BA", "PAMP.BA", "GOOGL.BA"])
def test_ba_symbols_share_one_market_data_contract(symbol: str) -> None:
    assert _detect_market(symbol) == "ar_equity"
    assert code_currency(symbol) == "ARS"
    assert detect_source(symbol) == "yahoo"
    assert _detect_source(symbol) == "yahoo"
    assert yahoo_is_supported(symbol)
    assert _to_yfinance_symbol(symbol) == symbol
    assert _market_for(symbol) == "ar"


def test_argentina_fallback_chain_is_yahoo_first() -> None:
    assert FALLBACK_CHAINS["ar_equity"] == ["yahoo", "yfinance", "local"]


def test_argentina_backtest_fails_closed_until_execution_rules_exist() -> None:
    with pytest.raises(ValueError, match="Argentina backtest execution rules are not modeled"):
        _create_market_engine("yahoo", {}, ["GGAL.BA"])
