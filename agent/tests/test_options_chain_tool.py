"""Tests for the get_options_chain tool.

All HTTP is mocked at ``yahoo_client.get_options`` (the client function the tool
imports), so no test ever reaches a live Yahoo endpoint.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.tools import options_chain_tool as oc


def _sample_result() -> dict:
    return {
        "expirationDates": [1750000000, 1750604800],
        "strikes": [190.0, 195.0, 200.0],
        "options": [
            {
                "expirationDate": 1750000000,
                "calls": [
                    {
                        "contractSymbol": "AAPL250101C00190000",
                        "strike": 190.0,
                        "lastPrice": 12.5,
                        "bid": 12.3,
                        "ask": 12.7,
                        "volume": 1500,
                        "openInterest": 8000,
                        "impliedVolatility": 0.2841,
                        "inTheMoney": True,
                        "expiration": 1750000000,
                    }
                ],
                "puts": [
                    {
                        "contractSymbol": "AAPL250101P00190000",
                        "strike": 190.0,
                        "lastPrice": 3.1,
                        "bid": 3.0,
                        "ask": 3.2,
                        "volume": 900,
                        "openInterest": 4200,
                        "impliedVolatility": 0.3012,
                        "inTheMoney": False,
                        "expiration": 1750000000,
                    }
                ],
            }
        ],
    }


class TestOptionsChainSuccess:
    """Happy-path envelope shape and field normalization."""

    def test_success_envelope_normalizes_contracts(self):
        with patch.object(
            oc.yahoo_client, "get_options", return_value=_sample_result()
        ) as mock_get:
            out = oc.OptionsChainTool().execute(ticker="AAPL.US")

        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["market"] == "us"
        assert payload["source"] == "yahoo"

        data = payload["data"]
        assert data["ticker"] == "AAPL.US"
        assert data["expiration"] == 1750000000
        assert data["expirations"] == [1750000000, 1750604800]
        assert data["calls_count"] == 1
        assert data["puts_count"] == 1

        call = data["calls"][0]
        assert call["contract_symbol"] == "AAPL250101C00190000"
        assert call["strike"] == 190.0
        assert call["implied_volatility"] == 0.2841
        assert call["open_interest"] == 8000
        assert call["in_the_money"] is True

        put = data["puts"][0]
        assert put["in_the_money"] is False
        assert put["bid"] == 3.0

        # Ticker flows through unchanged; no expiration -> nearest.
        _, kwargs = mock_get.call_args
        assert kwargs["expiration"] is None

    def test_explicit_expiration_passed_through(self):
        with patch.object(
            oc.yahoo_client, "get_options", return_value=_sample_result()
        ) as mock_get:
            oc.OptionsChainTool().execute(ticker="AAPL", expiration="1750000000")
        _, kwargs = mock_get.call_args
        assert kwargs["expiration"] == 1750000000

    def test_empty_chain_is_ok_with_zero_contracts(self):
        with patch.object(oc.yahoo_client, "get_options", return_value={}):
            out = oc.OptionsChainTool().execute(ticker="AAPL")
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["calls"] == []
        assert payload["data"]["puts"] == []
        assert payload["data"]["expiration"] is None

    def test_contracts_capped(self):
        bloated = _sample_result()
        bloated["options"][0]["calls"] = [
            {"strike": float(i)} for i in range(500)
        ]
        with patch.object(oc.yahoo_client, "get_options", return_value=bloated):
            out = oc.OptionsChainTool().execute(ticker="AAPL")
        payload = json.loads(out)
        assert payload["data"]["calls_count"] == oc._MAX_CONTRACTS_PER_SIDE

    def test_atm_uses_quote_and_full_ladder_before_capping(self):
        result = _sample_result()
        result["quote"] = {"regularMarketPrice": 337.4}
        result["options"][0]["calls"] = [
            {"strike": float(i)} for i in range(100, 401)
        ]
        data = json.loads(oc._success("AAPL", result))["data"]
        assert data["underlying_price"] == 337.4
        assert data["atm_strike"] == 337.0
        assert len(data["calls"]) == oc._MAX_CONTRACTS_PER_SIDE
        assert all(row["strike"] != data["atm_strike"] for row in data["calls"])

    @pytest.mark.parametrize("quote", [None, {}, {"regularMarketPrice": None},
        {"regularMarketPrice": True}, {"regularMarketPrice": 0},
        {"regularMarketPrice": float("nan")}, {"regularMarketPrice": "337.4"}])
    def test_missing_or_invalid_quote_never_guesses_atm(self, quote):
        result = _sample_result()
        result["quote"] = quote
        data = json.loads(oc._success("AAPL", result))["data"]
        assert data["underlying_price"] is None
        assert data["atm_strike"] is None


class TestOptionsChainErrors:
    """Error envelopes: missing ticker, bad expiration, upstream failure."""

    def test_missing_ticker_returns_error_envelope(self):
        out = oc.OptionsChainTool().execute(ticker="  ")
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "required" in payload["error"]

    def test_bad_expiration_returns_error_envelope(self):
        out = oc.OptionsChainTool().execute(ticker="AAPL", expiration="not-an-int")
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "epoch" in payload["error"]

    def test_upstream_failure_becomes_error_envelope(self):
        with patch.object(
            oc.yahoo_client,
            "get_options",
            side_effect=RuntimeError("HTTP 429 banned"),
        ):
            out = oc.OptionsChainTool().execute(ticker="AAPL")
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "yahoo options request failed" in payload["error"]
        assert "429" in payload["error"]


class TestExplicitExpirationValidation:
    """An explicit ``expiration`` must match what Yahoo actually returned.

    Yahoo answers a ``date`` it does not list with the default (nearest)
    chain, so before this validation a wrong-cycle date came back as
    ``ok: true`` with another expiration's contracts — or zero contracts —
    and nothing in the envelope said so.
    """

    def test_explicit_valid_expiration_passes_validation(self):
        with patch.object(oc.yahoo_client, "get_options", return_value=_sample_result()):
            out = oc.OptionsChainTool().execute(ticker="AAPL.US", expiration=1750000000)
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["expiration"] == 1750000000
        assert payload["data"]["calls_count"] == 1
        assert payload["data"]["puts_count"] == 1

    def test_invalid_expiration_returns_error_with_available_dates(self):
        with patch.object(oc.yahoo_client, "get_options", return_value=_sample_result()):
            out = oc.OptionsChainTool().execute(ticker="AAPL.US", expiration=9999999999)
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "not among the available" in payload["error"]
        assert "1750000000" in payload["error"]

    def test_explicit_expiration_without_expiration_dates_is_malformed(self):
        result_no_dates = {"options": [{"expirationDate": 1750000000, "calls": [], "puts": []}]}
        with patch.object(oc.yahoo_client, "get_options", return_value=result_no_dates):
            out = oc.OptionsChainTool().execute(ticker="AAPL.US", expiration=1750000000)
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "malformed" in payload["error"].lower()

    def test_expiration_dates_not_a_list_is_malformed(self):
        malformed = {"expirationDates": "not-a-list", "options": []}
        with patch.object(oc.yahoo_client, "get_options", return_value=malformed):
            out = oc.OptionsChainTool().execute(ticker="AAPL.US", expiration=1750000000)
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "malformed" in payload["error"].lower()

    def test_listed_expiration_with_empty_options_is_an_error(self):
        """Listed date but no chain block: an error, not ok:true with 0 contracts."""
        no_options = {"expirationDates": [1750000000], "options": []}
        with patch.object(oc.yahoo_client, "get_options", return_value=no_options):
            out = oc.OptionsChainTool().execute(ticker="AAPL.US", expiration=1750000000)
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "no option chain" in payload["error"].lower()
        assert "1750000000" in payload["error"]

    def test_block_expiration_mismatch_is_an_error(self):
        mismatch = {
            "expirationDates": [1750000000, 1750604800],
            "options": [{"expirationDate": 1750604800, "calls": [], "puts": []}],
        }
        with patch.object(oc.yahoo_client, "get_options", return_value=mismatch):
            out = oc.OptionsChainTool().execute(ticker="AAPL.US", expiration=1750000000)
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "did not match" in payload["error"]
        assert "1750604800" in payload["error"]

    def test_non_dict_options_block_is_malformed_not_a_crash(self):
        malformed = {
            "expirationDates": [1750000000],
            "options": [None, {"expirationDate": 1750000000, "calls": [], "puts": []}],
        }
        with patch.object(oc.yahoo_client, "get_options", return_value=malformed):
            out = oc.OptionsChainTool().execute(ticker="AAPL.US", expiration=1750000000)
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "malformed" in payload["error"].lower()

    def test_omitted_expiration_is_not_validated(self):
        """No expiration → nearest chain, passthrough; an empty result stays ok."""
        with patch.object(oc.yahoo_client, "get_options", return_value={"expirationDates": [], "options": []}):
            out = oc.OptionsChainTool().execute(ticker="AAPL.US")
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["calls_count"] == 0
