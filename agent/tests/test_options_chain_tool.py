"""Agent tool → shared gateway → observed-source adapter, without network."""

import json
from unittest.mock import Mock
import pytest
from src.tools.options_chain_tool import OptionsChainTool
from src.data_gateway.config import Config
from src.data_gateway.service import MarketDataGateway
from src.data_gateway.sources import yahoo_options
from backtest.loaders import yahoo_client


@pytest.fixture
def source(monkeypatch, tmp_path):
    expiration = 1893456000

    def row(kind):
        return {
            "contractSymbol": f"AAPL300101{kind}00190000",
            "strike": 190,
            "expiration": expiration,
            "bid": 3,
            "ask": 4,
            "lastPrice": 3.5,
        }

    raw = {
        "expirationDates": [expiration],
        "quote": {"symbol": "AAPL", "regularMarketPrice": 200},
        "options": [{"expirationDate": expiration, "calls": [row("C")], "puts": [row("P")]}],
    }
    fetch = Mock(return_value=raw)
    monkeypatch.setattr(yahoo_client, "get_options", fetch)
    gateway = MarketDataGateway(
        Config(cache_dir=tmp_path, sources=("yahoo",)), {"options_chain": {"yahoo": yahoo_options}}
    )
    monkeypatch.setattr("src.data_gateway.get_gateway", lambda: gateway)
    yield fetch
    gateway.close()


def test_tool_returns_same_gateway_metadata_and_canonical_cache_identity(source):
    first = json.loads(OptionsChainTool().execute(ticker="AAPL.US", expiration="1893456000"))
    assert first["ok"] and first["source"] == "yahoo"
    assert first["data"]["ticker"] == "AAPL"
    assert first["data"]["calls"][0]["contract_symbol"] == "AAPL300101C00190000"
    assert first["data"]["calls"][0]["delta"] is None
    assert first["gateway"]["executable"] is False
    assert json.loads(OptionsChainTool().execute(ticker="AAPL", expiration=1893456000))["gateway"]["cache"] == "fresh"
    source.assert_called_once_with("AAPL", expiration=1893456000)


@pytest.mark.parametrize("expiration", [True, 1.5, "not-an-int", -1, float("inf")])
def test_bad_expiration_never_calls_a_source(source, expiration):
    payload = json.loads(OptionsChainTool().execute(ticker="AAPL", expiration=expiration))
    assert not payload["ok"]
    source.assert_not_called()


def test_missing_ticker(source):
    assert not json.loads(OptionsChainTool().execute(ticker=" "))["ok"]
    source.assert_not_called()


@pytest.mark.parametrize("failure", ["empty", "mismatch", "dates", "network"])
def test_upstream_failure_is_explicit_not_an_empty_success(source, failure):
    if failure == "empty":
        source.return_value = {}
    elif failure == "mismatch":
        source.return_value["options"][0]["expirationDate"] = 1894060800
    elif failure == "dates":
        source.return_value["expirationDates"] = "invalid"
    else:
        source.side_effect = ConnectionError("unavailable")
    response = json.loads(OptionsChainTool().execute(ticker="AAPL", expiration=1893456000))
    assert not response["ok"]
    assert response["gateway"]["attempts"][0]["status"] == "unavailable"


def test_tool_caps_near_spot_without_losing_atm(source):
    source.return_value["options"][0]["calls"] = [
        {
            "contractSymbol": f"AAPL300101C{strike * 1000:08d}",
            "strike": strike,
            "expiration": 1893456000,
            "bid": 3,
            "ask": 4,
        }
        for strike in range(100, 301)
    ]
    response = json.loads(OptionsChainTool().execute(ticker="AAPL"))
    assert response["data"]["calls_count"] == 60
    assert any(row["strike"] == 200 for row in response["data"]["calls"])


def test_tool_pages_all_strikes_beyond_the_near_spot_window(source):
    for side, letter in (("calls", "C"), ("puts", "P")):
        source.return_value["options"][0][side] = [
            {
                "contractSymbol": f"AAPL300101{letter}{strike * 1000:08d}",
                "strike": strike,
                "expiration": 1893456000,
                "bid": 3,
                "ask": 4,
            }
            for strike in range(1, 301)
        ]
    response = json.loads(OptionsChainTool().execute(ticker="AAPL", offset=240))
    assert response["ok"]
    assert response["data"]["calls"][0]["strike"] == 241
    assert response["data"]["calls"][-1]["strike"] == 300
    assert response["data"]["next_offset"] is None
    assert not response["data"]["complete_expiration"]
