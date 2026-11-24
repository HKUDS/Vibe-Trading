"""European listings resolve to a market and are served by the Yahoo loaders (#2252).

``search_symbol`` handed back Yahoo's native ``SAP.DE`` / ``MC.PA`` spellings,
but no routing rule named those suffixes, so ``get_market_data`` and every tool
built on it refused them with ``Unsupported market identity``. These tests are
deterministic and make no network requests: Yahoo is mocked at the loader's
``yahoo_client.get_chart`` import site.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pandas as pd
import pytest

from backtest.engines._market_hooks import code_currency, matched_market
from backtest.engines.composite import _reject_mixed_currency
from backtest.loaders import yahoo_loader, yfinance_loader
from backtest.loaders.base import normalize_declared_quote_currency
from backtest.loaders.registry import FALLBACK_CHAINS, source_order_env_var
from backtest.loaders.yahoo_client import map_symbol
from backtest.loaders.yahoo_loader import _is_supported as yahoo_is_supported
from backtest.loaders.yfinance_loader import _to_yfinance_symbol
from backtest.runner import (
    _MARKET_TO_SOURCE,
    BacktestConfigSchema,
    _create_market_engine,
)
from src.agent.instrument_identity import _infer_currency, _infer_venue, _scan_symbols
from src.config.env_schema import DataConfig
from src.data_gateway.history_router import market_for
from src.market_data import data_market, detect_source, fetch_market_data
from src.tools.symbol_search_tool import _from_yahoo_symbol
from src.tools.technical_indicator_tool import TechnicalIndicatorTool

_MARKET = "europe_equity"

# symbol -> (quote currency, coarse venue). Includes the issue's four
# reproductions (SAP.DE, MC.PA and the UCITS ETFs EUNL.DE / SXR8.DE).
_LISTINGS: dict[str, tuple[str, str]] = {
    "SAP.DE": ("EUR", "xetra"),
    "EUNL.DE": ("EUR", "xetra"),
    "SXR8.DE": ("EUR", "xetra"),
    "MC.PA": ("EUR", "euronext_paris"),
    "ASML.AS": ("EUR", "euronext_amsterdam"),
    "ENI.MI": ("EUR", "borsa_italiana"),
    "NESN.SW": ("CHF", "six"),
    "PKO.WA": ("PLN", "gpw"),
}


def _rows(count: int = 2) -> list[dict]:
    """Daily Yahoo chart rows starting 2024-01-02 (UTC midnight)."""
    first = 1704153600
    return [
        {
            "trade_date": first + day * 86400,
            "open": 100.0 + day,
            "high": 101.0 + day,
            "low": 99.0 + day,
            "close": 100.5 + day,
            "volume": 1000 + day,
        }
        for day in range(count)
    ]


@pytest.mark.parametrize("symbol", sorted(_LISTINGS))
def test_european_listing_has_a_public_data_identity(symbol: str) -> None:
    assert matched_market(symbol) == _MARKET
    assert data_market(symbol) == _MARKET
    assert data_market(f" {symbol.lower()} ") == _MARKET
    assert market_for(symbol) == _MARKET
    assert detect_source(symbol) == "yahoo"


@pytest.mark.parametrize("symbol", sorted(_LISTINGS))
def test_quote_currency_follows_the_venue(symbol: str) -> None:
    currency, venue = _LISTINGS[symbol]
    assert code_currency(symbol) == currency
    assert _infer_currency(symbol) == currency
    assert _infer_venue(symbol) == venue


@pytest.mark.parametrize("symbol", sorted(_LISTINGS))
def test_identity_and_search_agree_with_the_data_layer(symbol: str) -> None:
    assert _scan_symbols(f"How did {symbol} trade last week?") == {symbol}
    assert _from_yahoo_symbol(symbol, {"quoteType": "ETF"}) == (symbol, "europe")


def test_lowercase_hosts_in_source_urls_are_not_read_as_symbols() -> None:
    text = "per https://www.boerse-frankfurt.de/etf and finanzen.de, 1COV.DE rose"
    assert _scan_symbols(text) == {"1COV.DE"}


@pytest.mark.parametrize("symbol", ["VOLV-B.ST", "BHP.AX", "SAP.XETRA"])
def test_venues_without_a_route_are_still_refused(symbol: str) -> None:
    with pytest.raises(ValueError, match="Unsupported market identity"):
        data_market(symbol)


def test_europe_fallback_chain_is_yahoo_first() -> None:
    assert FALLBACK_CHAINS[_MARKET] == ["yahoo", "yfinance", "local"]
    assert _MARKET_TO_SOURCE[_MARKET] == "yahoo"


def test_europe_source_order_override_has_a_typed_env_field() -> None:
    env_var = source_order_env_var(_MARKET)
    assert env_var == "MARKET_DATA_ORDER_EUROPE_EQUITY"
    assert DataConfig.model_fields["market_data_order_europe_equity"].alias == env_var


@pytest.mark.parametrize("symbol", sorted(_LISTINGS))
def test_both_yahoo_loaders_take_the_symbol_verbatim(symbol: str) -> None:
    assert _MARKET in yahoo_loader.DataLoader.markets
    assert _MARKET in yfinance_loader.DataLoader.markets
    assert yahoo_is_supported(symbol)
    assert map_symbol(symbol) == symbol
    assert _to_yfinance_symbol(symbol) == symbol


@pytest.mark.parametrize(
    ("symbol", "wrong"),
    [("SXR8.DE", "USD"), ("MC.PA", None), ("NESN.SW", "EUR"), ("PKO.WA", "EUR")],
)
def test_a_line_outside_the_venue_currency_is_refused(
    symbol: str, wrong: str | None
) -> None:
    frame = pd.DataFrame({"close": [100.0]})
    currency = _LISTINGS[symbol][0]
    kept = normalize_declared_quote_currency(frame.copy(), symbol, currency)
    assert kept.attrs["quote_currency"] == currency
    with pytest.raises(ValueError, match=currency):
        normalize_declared_quote_currency(frame.copy(), symbol, wrong)


@pytest.mark.parametrize("symbol", ["SAP.DE", "NESN.SW", "PKO.WA"])
def test_get_market_data_serves_european_bars_with_their_currency(symbol: str) -> None:
    currency = _LISTINGS[symbol][0]
    with patch(
        "backtest.loaders.yahoo_loader.yahoo_client.get_chart",
        return_value=(_rows(), currency),
    ) as mock_chart:
        payload = fetch_market_data(
            codes=[symbol],
            start_date="2024-01-01",
            end_date="2024-01-31",
            max_rows=0,
            include_provenance=True,
        )

    assert mock_chart.call_args.args[0] == symbol
    assert not payload.get("_unresolved")
    assert [row["close"] for row in payload[symbol]] == [100.5, 101.5]
    provenance = payload["_provenance"][symbol]
    assert provenance["source"] == "yahoo"
    assert provenance["quote_currency"] == currency
    assert provenance["quote_currency_basis"] == "source_metadata"


def test_technical_indicators_compute_for_a_ucits_etf() -> None:
    with patch(
        "backtest.loaders.yahoo_loader.yahoo_client.get_chart",
        return_value=(_rows(80), "EUR"),
    ):
        result = json.loads(
            TechnicalIndicatorTool().execute(
                symbol="EUNL.DE", lookback=60, end_date="2024-03-31"
            )
        )

    assert result["ok"] is True, result


@pytest.mark.parametrize("codes", [["SAP.DE"], ["AAPL.US", "MC.PA"], ["local:SAP.DE"]])
def test_data_support_never_enables_unimplemented_execution_rules(
    codes: list[str],
) -> None:
    with pytest.raises(ValueError, match="European backtest execution rules"):
        BacktestConfigSchema(
            codes=codes, start_date="2024-01-02", end_date="2024-01-31"
        )
    with pytest.raises(ValueError, match="European backtest execution rules"):
        _create_market_engine("yahoo", {}, codes)


def test_one_pool_never_mixes_european_currencies() -> None:
    _reject_mixed_currency(["SAP.DE", "MC.PA", "ASML.AS", "ENI.MI"])
    with pytest.raises(ValueError, match="one settlement currency"):
        _reject_mixed_currency(["SAP.DE", "NESN.SW"])
