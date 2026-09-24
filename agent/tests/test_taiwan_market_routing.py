"""Regression tests for Yahoo-served Taiwan (.TW / .TWO) market data.

These tests are deterministic and make no network requests: every Yahoo call is
mocked at the loader's ``yahoo_client.get_chart`` import site.  They pin the
data-path contract only: chain registration, the source mapping and the Yahoo
loaders' handling of the ``.TW`` / ``.TWO`` suffixes.  Symbol detection and the
engine are covered in ``test_market_detection.py`` and
``test_taiwan_backtest_smoke.py``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backtest.loaders import yahoo_loader, yfinance_loader
from backtest.loaders.registry import FALLBACK_CHAINS, source_order_env_var
from backtest.loaders.yahoo_client import map_symbol
from backtest.loaders.yahoo_loader import _is_supported as yahoo_is_supported
from backtest.loaders.yfinance_loader import _to_yfinance_symbol
from backtest.runner import _MARKET_TO_SOURCE
from src.config.env_schema import DataConfig

_MARKET = "taiwan_equity"

# 2330.TW is a TWSE listing, 6488.TWO a TPEx (OTC) listing.
_TW_SYMBOLS = ["2330.TW", "6488.TWO"]


def _rows() -> list[dict]:
    # 2024-01-02 and 2024-01-03 UTC midnights.
    return [
        {"trade_date": 1704153600, "open": 590.0, "high": 595.0, "low": 588.0, "close": 593.0, "volume": 1000},
        {"trade_date": 1704240000, "open": 593.0, "high": 600.0, "low": 592.0, "close": 598.0, "volume": 2000},
    ]


def test_taiwan_fallback_chain_is_yahoo_first() -> None:
    assert FALLBACK_CHAINS[_MARKET] == ["yahoo", "yfinance", "local"]


def test_taiwan_source_order_override_has_a_typed_env_field() -> None:
    env_var = source_order_env_var(_MARKET)
    assert env_var == "MARKET_DATA_ORDER_TAIWAN_EQUITY"
    assert DataConfig.model_fields["market_data_order_taiwan_equity"].alias == env_var


def test_taiwan_market_maps_to_yahoo_source() -> None:
    assert _MARKET_TO_SOURCE[_MARKET] == "yahoo"


def test_both_yahoo_loaders_declare_taiwan_market() -> None:
    assert _MARKET in yahoo_loader.DataLoader.markets
    assert _MARKET in yfinance_loader.DataLoader.markets


@pytest.mark.parametrize("symbol", _TW_SYMBOLS)
def test_yahoo_loader_accepts_taiwan_suffixes(symbol: str) -> None:
    assert yahoo_is_supported(symbol)
    assert yahoo_is_supported(symbol.lower())


@pytest.mark.parametrize("symbol", ["7203.T", "601398.SH", "2330.TWX"])
def test_yahoo_loader_rejects_non_taiwan_suffixes(symbol: str) -> None:
    assert not yahoo_is_supported(symbol)


@pytest.mark.parametrize("symbol", _TW_SYMBOLS)
def test_symbols_reach_both_yahoo_paths_unchanged(symbol: str) -> None:
    assert map_symbol(symbol) == symbol
    assert _to_yfinance_symbol(symbol) == symbol


@pytest.mark.parametrize("symbol", _TW_SYMBOLS)
def test_yahoo_fetch_returns_frame_for_taiwan_symbol(symbol: str) -> None:
    with patch(
        "backtest.loaders.yahoo_loader.yahoo_client.get_chart",
        return_value=(_rows(), "TWD"),
    ) as mock_chart:
        out = yahoo_loader.DataLoader().fetch([symbol], "2024-01-01", "2024-01-31")

    assert list(out) == [symbol]
    assert len(out[symbol]) == 2
    assert out[symbol]["close"].iloc[-1] == 598.0
    assert mock_chart.call_args.args[0] == symbol


def test_yahoo_fetch_skips_non_taiwan_suffix_without_a_request() -> None:
    with patch("backtest.loaders.yahoo_loader.yahoo_client.get_chart") as mock_chart:
        out = yahoo_loader.DataLoader().fetch(["7203.T"], "2024-01-01", "2024-01-31")

    assert out == {}
    mock_chart.assert_not_called()
