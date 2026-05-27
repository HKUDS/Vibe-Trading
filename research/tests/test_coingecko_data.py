"""
Tests for research/lib/coingecko_data.py.

Network-free: all requests.get calls are mocked. Verifies:
  (a) fetch_stablecoin_supply parses payload into a daily DataFrame.
  (b) Multi-coin aggregation sums per-day market caps.
  (c) Single-coin fetch failure does not crash the aggregate call.
  (d) Empty payload returns an empty DataFrame with the expected column.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

# Bootstrap research/ onto sys.path.
_RESEARCH_DIR = Path(__file__).resolve().parents[1]
if str(_RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_DIR))

from lib import coingecko_data
from lib.coingecko_data import fetch_stablecoin_supply


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Clear the lru_cache between tests so mocks aren't shared."""
    coingecko_data._fetch_market_caps_cached.cache_clear()


def _fake_response(market_caps: list[list]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"market_caps": market_caps}
    return resp


def test_single_coin_payload_parsed() -> None:
    ts_ms = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    payload = [[ts_ms, 100_000_000.0]]
    with patch("lib.coingecko_data.requests.get", return_value=_fake_response(payload)):
        df = fetch_stablecoin_supply(days=1, coin_ids=("tether",))
    assert not df.empty
    assert df.columns.tolist() == ["stablecoin_supply"]
    assert df["stablecoin_supply"].iloc[0] == pytest.approx(100_000_000.0)


def test_multi_coin_sums_market_caps() -> None:
    ts_ms = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    tether_payload = [[ts_ms, 100.0]]
    usdc_payload = [[ts_ms, 50.0]]

    call_order: list[str] = []

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        if "tether" in url:
            call_order.append("tether")
            return _fake_response(tether_payload)
        if "usd-coin" in url:
            call_order.append("usd-coin")
            return _fake_response(usdc_payload)
        raise AssertionError(f"unexpected url: {url}")

    with patch("lib.coingecko_data.requests.get", side_effect=fake_get):
        df = fetch_stablecoin_supply(days=1, coin_ids=("tether", "usd-coin"))

    assert set(call_order) == {"tether", "usd-coin"}
    assert df["stablecoin_supply"].iloc[0] == pytest.approx(150.0)


def test_single_coin_request_error_does_not_crash() -> None:
    ts_ms = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    good_payload = [[ts_ms, 42.0]]

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        if "tether" in url:
            raise requests.RequestException("simulated network error")
        return _fake_response(good_payload)

    with patch("lib.coingecko_data.requests.get", side_effect=fake_get):
        df = fetch_stablecoin_supply(days=1, coin_ids=("tether", "usd-coin"))

    # tether failed silently; usd-coin succeeded → aggregate is just usd-coin.
    assert df["stablecoin_supply"].iloc[0] == pytest.approx(42.0)


def test_empty_payload_returns_empty_frame() -> None:
    with patch("lib.coingecko_data.requests.get", return_value=_fake_response([])):
        df = fetch_stablecoin_supply(days=1, coin_ids=("tether",))
    assert df.empty
    assert "stablecoin_supply" in df.columns


def test_symbol_arg_ignored_does_not_affect_request() -> None:
    """The fetcher accepts ``symbol`` for registry-signature symmetry but
    must NOT inject it into the request params."""
    ts_ms = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    payload = [[ts_ms, 1.0]]

    captured_params: list[dict] = []

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        captured_params.append(dict(params or {}))
        return _fake_response(payload)

    with patch("lib.coingecko_data.requests.get", side_effect=fake_get):
        fetch_stablecoin_supply(symbol="BTC-USDT-SWAP", days=1, coin_ids=("tether",))

    assert captured_params, "requests.get was not called"
    assert "symbol" not in captured_params[0]
    assert "instId" not in captured_params[0]
