"""Offline NIFTY 100 loader tests; all prices and constituent rows are synthetic."""

from __future__ import annotations

import hashlib
import json
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

import src.market_data as market_data
import src.tools.alpha_bench_tool as tool
from backtest.engines._market_hooks import _detect_market
from backtest.loaders.yfinance_loader import _to_yfinance_symbol


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Unit tests must not make network requests")

    monkeypatch.setattr(requests, "get", reject)
    monkeypatch.setattr(market_data, "fetch_market_data", reject)


def roster(symbols=None, series="EQ"):
    """An invented 100-row roster, never an assertion of historical membership."""
    symbols = symbols if symbols is not None else [f"TEST{i}" for i in range(100)]
    return (
        "Company Name,Industry,Symbol,Series,ISIN Code\n"
        + "".join(
            f"Synthetic company,Fixture industry,{s},{series},FIXTURE\n"
            for s in symbols
        )
    ).encode()


def response(raw):
    result = Mock()
    result.content = raw
    result.raise_for_status.return_value = None
    return result


@pytest.fixture
def official(monkeypatch):
    get = Mock(return_value=response(roster()))
    monkeypatch.setattr(requests, "get", get)
    return get


def prices(codes):
    dates = pd.date_range("2024-01-02", periods=3, freq="B")
    result = {
        c: pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0],
                "high": [102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0],
                "close": [101.0, 102.0, 103.0],
                "volume": [1000.0, 1100.0, 1200.0],
            },
            index=dates,
        )
        for c in codes
    }
    result["_provenance"] = {
        c: {
            "source": "yahoo",
            "volume_unit": "shares",
            "currency": "INR",
            "price_caliber": "fixture",
        }
        for c in codes
    }
    result["_unresolved"] = []
    result["_diagnostics"] = {"fixture": True}
    return result


def test_official_csv_provenance_and_unknown_effective_date(official):
    codes, meta = tool._fetch_nifty100_constituents()
    assert codes == [f"TEST{i}.NS" for i in range(100)]
    assert meta["constituent_source"] == tool._NIFTY100_CONSTITUENT_URLS[0]
    assert meta["constituent_count"] == 100
    assert meta["constituent_sha256"] == hashlib.sha256(roster()).hexdigest()
    assert meta["constituent_source_date"] == meta["constituent_retrieved_at"][:10]
    assert meta["constituent_effective_date"] is None
    assert "not membership effective date" in meta["constituent_date_basis"]
    assert meta["constituent_fetch_failures"] == []
    assert not meta["constituent_fallback_used"]
    official.assert_called_once()
    assert official.call_args.args[0] == tool._NIFTY100_CONSTITUENT_URLS[0]
    assert official.call_args.kwargs["timeout"] == 20


@pytest.mark.parametrize(
    "symbol,expected",
    [
        (" reliance ", "RELIANCE.NS"),
        (" tcs.ns ", "TCS.NS"),
        ("m&m", "M&M.NS"),
        (" bajaj-auto ", "BAJAJ-AUTO.NS"),
    ],
)
def test_existing_india_symbol_conventions(official, symbol, expected):
    symbols = [symbol] + [f"TEST{i}" for i in range(99)]
    official.return_value = response(roster(symbols))
    codes, _ = tool._fetch_nifty100_constituents()
    assert codes[0] == expected
    assert _to_yfinance_symbol(codes[0]) == expected
    assert _detect_market(codes[0]) == "india_equity"
    assert market_data.detect_source(codes[0]) == "yahoo"


@pytest.mark.parametrize(
    "bad_csv",
    [
        b"<html>blocked</html>",
        b"Symbol\n",
        roster(["TEST"] * 100),
        roster([f"TEST{i}" for i in range(99)]),
        roster(series="BE"),
        roster(["bad ticker"] + [f"TEST{i}" for i in range(99)]),
        roster(["TCS.BO"] + [f"TEST{i}" for i in range(99)]),
        roster([""] + [f"TEST{i}" for i in range(99)]),
        roster(["test0.ns"] + [f"TEST{i}" for i in range(99)]),
    ],
)
def test_bad_roster_uses_only_identified_official_mirror(official, bad_csv):
    official.side_effect = [response(bad_csv), response(roster())]
    codes, meta = tool._fetch_nifty100_constituents()
    assert len(codes) == 100
    assert meta["constituent_fallback_used"]
    assert meta["constituent_source"] == tool._NIFTY100_CONSTITUENT_URLS[1]
    assert (
        meta["constituent_fetch_failures"][0]["source"]
        == tool._NIFTY100_CONSTITUENT_URLS[0]
    )
    assert [call.args[0] for call in official.call_args_list] == list(
        tool._NIFTY100_CONSTITUENT_URLS
    )


@pytest.mark.parametrize(
    "failure,reason",
    [
        (requests.Timeout("timeout"), "request timed out"),
        (requests.HTTPError("403"), "HTTP request failed"),
    ],
)
def test_transport_error_uses_mirror_with_provenance(official, failure, reason):
    official.side_effect = [failure, response(roster())]
    _, meta = tool._fetch_nifty100_constituents()
    assert meta["constituent_fallback_used"]
    assert reason == meta["constituent_fetch_failures"][0]["error"]


def test_both_sources_fail_without_inventing_members_or_requesting_prices(official):
    official.side_effect = requests.ConnectionError("offline")
    with pytest.raises(RuntimeError, match="no substitute universe"):
        tool._load_nifty100_panel("2024-01-01", "2024-12-31")
    assert official.call_count == 2


def test_dispatch_shared_fetch_and_metadata_keep_all_rows(monkeypatch, official):
    codes = [f"TEST{i}.NS" for i in range(100)]
    data = prices(codes)
    data[codes[0]].iloc[1, 3] = float("nan")
    fetch = Mock(return_value=data)
    monkeypatch.setattr(market_data, "fetch_market_data", fetch)
    panel = tool._load_universe_panel(
        "nifty100", "2024-01-01/2024-12-31", use_cache=False
    )
    fetch.assert_called_once_with(
        codes=codes,
        start_date="2024-01-01",
        end_date="2024-12-31",
        source="auto",
        include_provenance=True,
        as_frames=True,
        loader_resolver=market_data.get_loader,
    )
    assert tool._UNIVERSE_TAG["nifty100"] == "equity_in"
    assert len(panel["close"]) == 3
    assert pd.isna(panel["close"].loc[pd.Timestamp("2024-01-03"), codes[0]])
    assert "vwap" in panel and "sector" in panel
    assert panel["_meta"]["vwap_source"] == "ohlc4_approximation"
    assert panel["_meta"]["sector_classification"] == "NSE Industry"
    meta = panel["_meta"]
    assert meta["missing_observations"]["close"][codes[0]] == 1
    assert (
        meta["constituent_count"]
        == meta["requested_instruments"]
        == meta["fetched_instruments"]
        == 100
    )
    assert meta["survivorship_bias"] and not meta["point_in_time_membership"]
    assert not meta["degraded"]
    assert meta["currency"] == "INR"
    assert meta["price_provenance"] == data["_provenance"]
    assert meta["data_diagnostics"] == {"fixture": True}
    assert meta["price_sources"] == ["yahoo"]
    assert meta["missing_fields"] == []


def test_missing_empty_and_all_nan_instruments_are_visible(monkeypatch, official):
    codes = [f"TEST{i}.NS" for i in range(100)]
    data = prices(codes[1:])
    data[codes[1]] = pd.DataFrame()
    data[codes[2]]["close"] = float("nan")
    data["_unresolved"] = [codes[0]]
    monkeypatch.setattr(market_data, "fetch_market_data", lambda **kw: data)
    panel = tool._load_nifty100_panel("2024-01-01", "2024-12-31")
    assert panel["_meta"]["fetched_instruments"] == 97
    assert set(panel["_meta"]["missing_instruments"]) == set(codes[:3])
    assert panel["_meta"]["degraded"]
    assert panel["_meta"]["constituent_count"] == 100


def test_mirror_fallback_is_reported_even_with_full_price_coverage(
    monkeypatch, official
):
    official.side_effect = [requests.Timeout("timeout"), response(roster())]
    monkeypatch.setattr(
        market_data, "fetch_market_data", lambda **kw: prices(kw["codes"])
    )
    meta = tool._load_nifty100_panel("2024-01-01", "2024-12-31")["_meta"]
    assert meta["constituent_fallback_used"] and meta["degraded"]
    assert meta["fetched_instruments"] == meta["constituent_count"] == 100


@pytest.mark.parametrize("count", [0, 1])
def test_unusable_price_panel_fails_clearly(monkeypatch, official, count):
    monkeypatch.setattr(
        market_data, "fetch_market_data", lambda **kw: prices(kw["codes"][:count])
    )
    with pytest.raises(RuntimeError, match="fewer than two"):
        tool._load_nifty100_panel("2024-01-01", "2024-12-31")


def test_unrequested_instrument_is_rejected(monkeypatch, official):
    monkeypatch.setattr(
        market_data, "fetch_market_data", lambda **kw: prices(["AAPL.US", "TEST0.NS"])
    )
    with pytest.raises(RuntimeError, match="outside the NIFTY 100 request"):
        tool._load_nifty100_panel("2024-01-01", "2024-12-31")


def test_authenticated_panel_cache_preserves_constituent_provenance(
    monkeypatch, official, tmp_path
):
    monkeypatch.setattr(tool, "get_runtime_root", lambda: tmp_path)
    fetch = Mock(side_effect=lambda **kw: prices(kw["codes"]))
    monkeypatch.setattr(market_data, "fetch_market_data", fetch)
    first = tool._load_universe_panel("nifty100", "2024-2024")
    second = tool._load_universe_panel("nifty100", "2024-2024")
    assert first["_meta"] == second["_meta"]
    pd.testing.assert_frame_equal(first["close"], second["close"])
    official.assert_called_once()
    fetch.assert_called_once()
    cache = tmp_path / "cache" / "nifty100_2024-01-01_2024-12-31.pkl"
    assert cache.is_file()
    assert cache.with_suffix(".pkl.sha256").is_file()


# Deliberately fake sensitive strings; never real credentials or user paths.
PRIVATE_MARKERS = (
    "/private/SYNTHETIC_PATH_MARKER/credentials.pem",
    "SYNTHETIC_USERNAME:SYNTHETIC_PASSWORD",
    "SYNTHETIC_TOKEN_MARKER",
    "SYNTHETIC_ARBITRARY_DETAIL",
)
PRIVATE_ERROR = (
    "https://SYNTHETIC_USERNAME:SYNTHETIC_PASSWORD@proxy.invalid/"
    "?token=SYNTHETIC_TOKEN_MARKER " + PRIVATE_MARKERS[0] + " " + PRIVATE_MARKERS[3]
)


@pytest.mark.parametrize(
    "error_type,reason",
    [
        (requests.Timeout, "request timed out"),
        (requests.HTTPError, "HTTP request failed"),
        (requests.ConnectionError, "connection failed"),
        (requests.RequestException, "request failed"),
        (ValueError, "invalid constituent data"),
        (RuntimeError, "constituent source failed"),
    ],
)
@pytest.mark.parametrize("fallback_succeeds", [True, False])
def test_constituent_failures_never_echo_private_details(
    official, caplog, error_type, reason, fallback_succeeds
):
    failure = error_type(PRIVATE_ERROR)
    official.side_effect = [
        failure,
        response(roster()) if fallback_succeeds else failure,
    ]
    if fallback_succeeds:
        codes, metadata = tool._fetch_nifty100_constituents()
        assert len(codes) == 100
        assert metadata["constituent_fallback_used"]
        assert metadata["constituent_fetch_failures"][0]["error"] == reason
        output = json.dumps(metadata)
    else:
        with pytest.raises(RuntimeError, match="no substitute universe") as error:
            tool._fetch_nifty100_constituents()
        output = str(error.value)
        assert reason in output
        assert error.value.__context__ is None
    for marker in PRIVATE_MARKERS:
        assert marker not in output + caplog.text
    assert official.call_count == 2
