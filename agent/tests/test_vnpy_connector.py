"""Unit tests for the vn.py RPC bridge connector (no live vn.py process needed).

Covers config resolution, symbol parsing, and the fail-closed order gate.
Live RPC round-trip behavior (subscribe/send_order/query_history against a
real vn.py MainEngine) is exercised manually — see
src/trading/connectors/vnpy/sdk.py's module docstring for the setup.
"""

from __future__ import annotations

import pytest

from src.trading.connectors.vnpy import sdk


def test_build_config_defaults():
    cfg = sdk.build_config()
    assert cfg.req_address == sdk.DEFAULT_REQ_ADDRESS
    assert cfg.sub_address == sdk.DEFAULT_SUB_ADDRESS
    assert cfg.profile == "paper"
    assert cfg.assume_environment_verified is False


def test_build_config_profile_overrides():
    cfg = sdk.build_config({"profile": "live", "gateway_name": "CTP"}, {"timeout": 5})
    assert cfg.profile == "live"
    assert cfg.environment == "live"
    assert cfg.gateway_name == "CTP"
    assert cfg.timeout == 5


def test_invalid_profile_rejected():
    with pytest.raises(sdk.VnpyConfigError):
        sdk.VnpyConfig.from_mapping({"profile": "sandbox"})


def test_split_symbol():
    code, exchange = sdk._split_symbol("IF2406.CFFEX")
    assert code == "IF2406"
    assert exchange.value == "CFFEX"


def test_split_symbol_rejects_missing_exchange():
    with pytest.raises(sdk.VnpyConfigError):
        sdk._split_symbol("IF2406")


def test_split_symbol_rejects_unknown_exchange():
    with pytest.raises(sdk.VnpyConfigError):
        sdk._split_symbol("IF2406.NOTREAL")


def test_place_order_fails_closed_without_verification():
    cfg = sdk.VnpyConfig(gateway_name="CTP", assume_environment_verified=False)
    result = sdk.place_order(cfg, symbol="IF2406.CFFEX", side="buy", quantity=1)
    assert result["status"] == "error"
    assert "assume_environment_verified" in result["error"]


def test_place_order_requires_gateway_name():
    cfg = sdk.VnpyConfig(gateway_name="", assume_environment_verified=True)
    result = sdk.place_order(cfg, symbol="IF2406.CFFEX", side="buy", quantity=1)
    assert result["status"] == "error"
    assert "gateway_name" in result["error"]


def test_place_order_rejects_notional():
    cfg = sdk.VnpyConfig(gateway_name="CTP", assume_environment_verified=True)
    result = sdk.place_order(cfg, symbol="IF2406.CFFEX", side="buy", notional=1000)
    assert result["status"] == "error"
    assert "notional" in result["error"]


def test_cancel_order_fails_closed_without_verification():
    cfg = sdk.VnpyConfig(assume_environment_verified=False)
    result = sdk.cancel_order(cfg, order_id="CTP.123", symbol="IF2406.CFFEX")
    assert result["status"] == "error"
    assert "assume_environment_verified" in result["error"]
