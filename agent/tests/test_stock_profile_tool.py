"""Tests for the get_stock_profile tool.

All HTTP is mocked at :func:`get_quote_summary` as it is imported into the tool
module, so no test touches a live Yahoo Finance endpoint.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from src.tools import stock_profile_tool as sp


def _sample_summary() -> dict:
    return {
        "price": {
            "symbol": "AAPL",
            "exchange": "NMS",
            "exchangeName": "NasdaqGS",
            "fullExchangeName": "NasdaqGS",
            "quoteType": "EQUITY",
            "currency": "USD",
        },
        "defaultKeyStatistics": {
            "forwardPE": {"raw": 28.5, "fmt": "28.50"},
            "trailingEps": {"raw": 6.13},
            "beta": {"raw": 1.25},
            "heldPercentInstitutions": {"raw": 0.61},
            "sharesOutstanding": {"raw": 15_000_000_000},
        },
        "financialData": {
            "currentPrice": {"raw": 195.0},
            "targetMeanPrice": {"raw": 210.0},
            "recommendationKey": "buy",
            "numberOfAnalystOpinions": {"raw": 40},
            "returnOnEquity": {"raw": 1.47},
            "financialCurrency": "USD",
        },
        "earningsTrend": {
            "trend": [
                {
                    "period": "0q",
                    "endDate": "2026-06-30",
                    "growth": {"raw": 0.08},
                    "earningsEstimate": {
                        "avg": {"raw": 1.34},
                        "low": {"raw": 1.30},
                        "high": {"raw": 1.40},
                        "numberOfAnalysts": {"raw": 28},
                    },
                    "revenueEstimate": {"avg": {"raw": 89_000_000_000}},
                }
            ]
        },
        "institutionOwnership": {
            "ownershipList": [
                {
                    "organization": "Vanguard Group Inc",
                    "reportDate": {"raw": 1_711_843_200},
                    "pctHeld": {"raw": 0.084},
                    "position": {"raw": 1_300_000_000},
                    "value": {"raw": 250_000_000_000},
                }
            ]
        },
        "insiderHolders": {
            "holders": [
                {
                    "name": "COOK TIMOTHY D",
                    "relation": "Chief Executive Officer",
                    "latestTransDate": "2026-04-01",
                    "positionDirect": {"raw": 3_280_000},
                }
            ]
        },
        "recommendationTrend": {
            "trend": [
                {
                    "period": "0m",
                    "strongBuy": 12,
                    "buy": 20,
                    "hold": 8,
                    "sell": 1,
                    "strongSell": 0,
                }
            ]
        },
    }


class TestStockProfileSuccess:
    """Happy-path envelope shape and section shaping."""

    def test_default_returns_all_sections(self):
        with patch.object(
            sp, "get_quote_summary", return_value=_sample_summary()
        ) as mock_get:
            out = sp.StockProfileTool().execute(ticker="AAPL.US")

        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["market"] == "us"
        assert payload["source"] == "yahoo"
        data = payload["data"]
        assert data["ticker"] == "AAPL.US"
        assert set(data["sections"]) == set(sp._ALL_SECTIONS)

        # Listing identity is independent of, and alongside, the sections.
        assert data["listing"]["symbol"] == "AAPL"
        assert data["listing"]["exchange"] == "NMS"
        assert data["listing"]["currency"] == "USD"
        assert data["listing"]["financial_currency"] == "USD"

        # raw cells are unwrapped to scalars.
        assert data["sections"]["key_stats"]["forwardPE"] == 28.5
        assert data["sections"]["financials"]["recommendationKey"] == "buy"

        # list sections are projected into compact rows.
        est = data["sections"]["earnings_trend"][0]
        assert est["period"] == "0q"
        assert est["eps_avg"] == 1.34
        assert est["eps_analysts"] == 28

        inst = data["sections"]["institution_ownership"][0]
        assert inst["organization"] == "Vanguard Group Inc"
        assert inst["pct_held"] == 0.084

        insider = data["sections"]["insider_holders"][0]
        assert insider["name"] == "COOK TIMOTHY D"
        assert insider["position"] == 3_280_000

        rec = data["sections"]["recommendation_trend"][0]
        assert rec["strong_buy"] == 12

        # Default fans out to all six Yahoo modules, plus the listing module.
        _, args, kwargs = mock_get.mock_calls[0]
        requested_modules = args[1]
        assert "defaultKeyStatistics" in requested_modules
        assert "recommendationTrend" in requested_modules
        assert "price" in requested_modules
        assert len(requested_modules) == len(sp._ALL_SECTIONS) + 1

    def test_section_subset_only_requests_those_modules(self):
        with patch.object(
            sp, "get_quote_summary", return_value=_sample_summary()
        ) as mock_get:
            out = sp.StockProfileTool().execute(
                ticker="00700.HK", sections=["financials", "financials"]
            )

        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["market"] == "hk"
        # De-duplicated subset only.
        assert list(payload["data"]["sections"]) == ["financials"]

        _, args, _ = mock_get.mock_calls[0]
        # Listing module is always requested alongside the chosen sections.
        assert args[1] == ["price", "financialData"]

    def test_missing_module_yields_empty_shaped_section(self):
        # Yahoo can omit a module for a symbol; shaper must not crash.
        with patch.object(sp, "get_quote_summary", return_value={}):
            out = sp.StockProfileTool().execute(
                ticker="AAPL.US", sections=["key_stats", "insider_holders"]
            )
        data = json.loads(out)["data"]["sections"]
        assert data["key_stats"]["forwardPE"] is None
        assert data["insider_holders"] == []


class TestStockProfileErrors:
    """Error envelopes: missing ticker, bad section, upstream failure."""

    def test_missing_ticker_returns_error_envelope(self):
        out = sp.StockProfileTool().execute(ticker="  ")
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "required" in payload["error"]

    def test_unknown_section_returns_error_envelope(self):
        out = sp.StockProfileTool().execute(ticker="AAPL.US", sections=["bogus"])
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "unknown section" in payload["error"]

    def test_upstream_failure_becomes_error_envelope(self):
        with patch.object(
            sp, "get_quote_summary", side_effect=RuntimeError("HTTP 429 banned")
        ):
            out = sp.StockProfileTool().execute(ticker="AAPL.US")
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "yahoo quoteSummary request failed" in payload["error"]
        assert "429" in payload["error"]


def test_uk_ticker_market_label() -> None:
    """VOD.L is served by Yahoo but must not be labeled 'us' (#1206)."""
    from src.tools.stock_profile_tool import _market_for

    assert _market_for("VOD.L") == "uk"
    assert _market_for("BARC.L") == "uk"
    assert _market_for("AAPL.US") == "us"
    assert _market_for("AAPL") == "us"
    assert _market_for("00700.HK") == "hk"


def test_listing_identity_independent_of_fundamentals() -> None:
    """A secondary listing keeps the issuer's fundamentals but its own venue (#1567)."""
    primary_summary = _sample_summary()
    with patch.object(sp, "get_quote_summary", return_value=primary_summary):
        primary = json.loads(sp.StockProfileTool().execute(ticker="AAPL.US"))

    secondary_summary = _sample_summary()
    secondary_summary["price"] = {
        "symbol": "GOOGL.BA",
        "exchange": "BUE",
        "exchangeName": "Buenos Aires",
        "fullExchangeName": "Buenos Aires Stock Exchange",
        "quoteType": "EQUITY",
        "currency": "ARS",
    }
    with patch.object(sp, "get_quote_summary", return_value=secondary_summary):
        secondary = json.loads(sp.StockProfileTool().execute(ticker="GOOGL.BA"))

    # Same issuer fundamentals regardless of listing.
    assert primary["data"]["sections"] == secondary["data"]["sections"]

    # Listing identity is independently available and reflects the venue.
    assert primary["data"]["listing"]["currency"] == "USD"
    assert secondary["data"]["listing"]["currency"] == "ARS"
    assert (
        primary["data"]["listing"]["exchange"]
        != secondary["data"]["listing"]["exchange"]
    )


def test_listing_identity_omits_financial_currency_when_not_fetched() -> None:
    """financial_currency is only surfaced when the financials module is fetched."""
    summary = _sample_summary()
    del summary["financialData"]
    with patch.object(sp, "get_quote_summary", return_value=summary):
        out = sp.StockProfileTool().execute(ticker="AAPL.US", sections=["key_stats"])

    listing = json.loads(out)["data"]["listing"]
    assert "financial_currency" not in listing


def test_listing_identity_underlying_symbol_only_when_yahoo_supplies_it(monkeypatch) -> None:
    """The underlying-issuer link is never inferred, only passed through (#1567)."""
    summary = _sample_summary()
    with patch.object(sp, "get_quote_summary", return_value=summary):
        out = sp.StockProfileTool().execute(ticker="AAPL.US")
    assert "underlying_symbol" not in json.loads(out)["data"]["listing"]

    # A new upstream observation requires a cache miss; the first snapshot
    # correctly retains the provider's earlier absence until it expires.
    from src.data_gateway import get_gateway
    monkeypatch.setattr(get_gateway().cache, "get", lambda _: None)
    summary["price"]["underlyingSymbol"] = "AAPL"
    with patch.object(sp, "get_quote_summary", return_value=summary):
        out = sp.StockProfileTool().execute(ticker="AAPL.US")
    assert json.loads(out)["data"]["listing"]["underlying_symbol"] == "AAPL"
