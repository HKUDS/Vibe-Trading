"""Offline tests for the alpha-bench field availability contract."""

from __future__ import annotations

import json

import pandas as pd

from src.factors.data_availability import (
    MarketContext,
    build_availability_contract,
    register_availability_adapter,
)


def _panel() -> dict:
    index = pd.date_range("2026-01-02", periods=2, freq="D")
    return {
        "close": pd.DataFrame({"600519.SH": [10.0, 10.2]}, index=index),
        "fund:revenue": pd.DataFrame({"600519.SH": [100.0, 100.0]}, index=index),
        "_meta": {
            "pit_membership": True,
            "survivorship_bias": False,
            "constituent_source": "tushare index_weight",
            "fundamental_source": "sec",
        },
    }


def _fields(contract: dict) -> dict[str, dict]:
    return {item["field"]: item for item in contract["fields"]}


def test_contract_distinguishes_verified_assumed_unknown_and_failed() -> None:
    contract = build_availability_contract(
        _panel(),
        universe="csi300",
        period="2026-01-01/2026-01-31",
        required_fields=["fund:revenue", "fund:eps"],
    )

    fields = _fields(contract)
    assert contract["schema"] == "alpha-bench.data-availability/v1"
    assert contract["asset_class"] == "equity"
    assert contract["venue"] == "XSHG+XSHE"
    assert fields["universe:membership"]["status"] == "verified"
    assert fields["universe:membership"]["source"] == "tushare index_weight"
    assert fields["universe:membership"]["pit_safe"] is True
    assert fields["close"]["status"] == "assumed"
    assert fields["close"]["pit_safe"] is False
    assert fields["fund:revenue"]["status"] == "unknown"
    assert fields["fund:revenue"]["pit_safe"] is False
    assert "timestamp" in fields["fund:revenue"]["reason"]
    assert fields["fund:eps"]["status"] == "failed"
    assert fields["fund:eps"]["validation"]["present"] is False
    assert any("timestamp" in warning for warning in contract["warnings"])
    json.dumps(contract)


def test_exact_field_timestamp_can_be_verified() -> None:
    panel = {
        "close": pd.DataFrame(
            {"AAPL.US": [100.0]}, index=pd.DatetimeIndex(["2026-01-02"])
        ),
        "fund:revenue": pd.DataFrame(
            {"AAPL.US": [10.0]}, index=pd.DatetimeIndex(["2026-01-02"])
        ),
        "_meta": {
            "price_sources": ["yfinance"],
            "fundamental_source": "sec",
            "field_fingerprints": {"close": "sha256:bars"},
            "field_availability": {
                "close": {
                    "observation_date": "2026-01-02",
                    "available_at": "2026-01-02T21:00:00Z",
                    "pit_safe": True,
                },
                "fund:revenue": {
                    "available_at": "2026-01-02T16:00:00Z",
                    "pit_safe": True,
                },
            },
        },
    }

    close = _fields(build_availability_contract(panel, universe="sp500"))["close"]
    assert close["status"] == "verified"
    assert close["pit_safe"] is True
    assert close["observation_date"] == "2026-01-02"
    assert close["available_at"] == "2026-01-02T21:00:00Z"
    assert close["fingerprint"] == "sha256:bars"
    assert _fields(build_availability_contract(panel, universe="sp500"))["fund:revenue"]["status"] == "verified"


def test_future_market_can_register_an_adapter_without_runner_changes() -> None:
    class _FutureAdapter:
        name = "future_market"

        def context(self, universe, metadata):
            del universe, metadata
            return MarketContext("future", "XNEW", "USD", "UTC", "XNEW")

        def field_policy(self, field, metadata):
            del field, metadata
            return {"kind": "bar", "availability_mode": "bar_close"}

    register_availability_adapter("future-market", _FutureAdapter())
    panel = {
        "close": pd.DataFrame(
            {"NEW1": [1.0]}, index=pd.DatetimeIndex(["2026-01-02"])
        ),
        "_meta": {"price_sources": ["new-feed"]},
    }

    contract = build_availability_contract(panel, universe="future-market")
    assert contract["adapter"] == "future_market"
    assert contract["asset_class"] == "future"
    assert _fields(contract)["close"]["source"] == "new-feed"


def test_metadata_without_source_is_explicitly_unknown() -> None:
    panel = {
        "close": pd.DataFrame(
            {"X": [1.0]}, index=pd.DatetimeIndex(["2026-01-02"])
        )
    }
    close = _fields(build_availability_contract(panel, universe="unregistered"))["close"]
    assert close["status"] == "unknown"
    assert close["source"] is None
    assert close["pit_safe"] is False
