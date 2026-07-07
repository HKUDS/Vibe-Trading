"""Tests for connector-first trading profile operations."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.trading import profiles, service
from src.tools import build_registry
from src.tools.trading_connector_tool import TradingPlaceOrderTool, TradingSelectConnectionTool

pytestmark = pytest.mark.unit


def _agent_config(server) -> SimpleNamespace:
    return SimpleNamespace(mcp_servers={"robinhood": server})


def test_remote_call_requires_enabled_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generic remote reads must respect the operator MCP allowlist."""
    server = SimpleNamespace(
        url="https://agent.robinhood.com/mcp/trading",
        enabled_tools=["get_portfolio"],
        auth=SimpleNamespace(cache_dir="/tmp/vibe-no-token"),
    )
    monkeypatch.setattr("src.config.loader.load_agent_config", lambda: _agent_config(server))
    monkeypatch.setattr("src.live.registry.has_cached_oauth_token", lambda *_: True)

    result = service.get_positions("robinhood-live-mcp")

    assert result["status"] == "error"
    assert "not enabled" in result["error"]


def test_remote_call_requires_cached_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generic remote reads must not trigger OAuth from tool/API/MCP paths."""
    server = SimpleNamespace(
        url="https://agent.robinhood.com/mcp/trading",
        enabled_tools=["get_equity_positions"],
        auth=SimpleNamespace(cache_dir="/tmp/vibe-no-token"),
    )
    monkeypatch.setattr("src.config.loader.load_agent_config", lambda: _agent_config(server))
    monkeypatch.setattr("src.live.registry.has_cached_oauth_token", lambda *_: False)

    result = service.get_positions("robinhood-live-mcp")

    assert result["status"] == "not_authorized"
    assert "connector authorize robinhood-live-mcp" in result["error"]


def test_ibkr_official_profile_does_not_advertise_unknown_generic_reads() -> None:
    """IBKR official MCP stays honest until stable remote tool names are known."""
    profile = profiles.profile_by_id("ibkr-live-official-mcp-readonly")

    assert profile.capabilities == ("mcp.read.discovery",)
    result = service.get_account(profile.id)
    assert result["status"] == "error"
    assert "does not support" in result["error"]


def test_connector_profile_id_for_broker_prefers_live_remote_mcp() -> None:
    """Broker on-ramps should resolve through the centralized profile registry."""
    assert service.connector_profile_id_for_broker("robinhood") == "robinhood-live-mcp"
    assert service.connector_profile_id_for_broker("ibkr") == "ibkr-live-official-mcp-readonly"
    assert service.connector_profile_id_for_broker("futurebroker") == "futurebroker-live-mcp"


def test_select_connection_tool_returns_canonical_profile_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Selecting a profile should persist and return the canonical id."""
    monkeypatch.setattr(profiles, "get_runtime_root", lambda: tmp_path)

    result = TradingSelectConnectionTool().execute(connection="IBKR-PAPER-LOCAL")

    assert result
    payload = json.loads(result)
    assert payload["status"] == "ok"
    assert payload["selected_profile"] == "ibkr-paper-local"
    assert profiles.load_selected_profile_id() == "ibkr-paper-local"


def test_place_order_tool_treats_zero_unused_sizing_field_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM-filled zero quantity/notional fields must not violate sizing XOR."""
    calls: list[dict] = []

    def fake_place_order(symbol, connection, **kwargs):  # noqa: ANN001
        calls.append({"symbol": symbol, "connection": connection, **kwargs})
        return {"status": "ok", "echo": kwargs}

    monkeypatch.setattr("src.tools.trading_connector_tool.place_order", fake_place_order)

    quantity_result = json.loads(
        TradingPlaceOrderTool().execute(
            symbol="NVDA",
            connection="alpaca-paper-trade",
            side="buy",
            quantity=2,
            notional=0,
        )
    )
    notional_result = json.loads(
        TradingPlaceOrderTool().execute(
            symbol="NVDA",
            connection="alpaca-paper-trade",
            side="buy",
            quantity=0,
            notional=50,
        )
    )

    assert quantity_result["status"] == "ok"
    assert notional_result["status"] == "ok"
    assert calls[0]["quantity"] == 2.0
    assert calls[0]["notional"] is None
    assert calls[1]["quantity"] is None
    assert calls[1]["notional"] == 50.0


def test_live_broker_mcp_wrappers_are_hidden_from_agent_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connector-first registry must not expose broker-specific mcp_* tools."""
    server = SimpleNamespace(
        url="https://agent.robinhood.com/mcp/trading",
        enabled_tools=["get_positions"],
        auth=SimpleNamespace(cache_dir="/tmp/vibe-token"),
    )
    agent_config = SimpleNamespace(mcp_servers={"robinhood": server})
    monkeypatch.setattr("src.live.registry.is_live_broker", lambda *_: True)
    monkeypatch.setattr("src.live.registry.should_register_live_channel", lambda **_: True)

    def fail_build_wrappers(*_, **__):
        raise AssertionError("live broker wrappers should not be registered directly")

    monkeypatch.setattr("src.tools.mcp.build_mcp_tool_wrappers", fail_build_wrappers)

    registry = build_registry(agent_config=agent_config, include_shell_tools=False)

    assert "trading_positions" in registry.tool_names
    assert not any(name.startswith("mcp_robinhood_") for name in registry.tool_names)


def test_robinhood_generic_reads_use_current_agentic_mcp_tool_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for #381: generic reads must not call stale Robinhood tool names."""
    calls: list[tuple[str, dict]] = []
    server = SimpleNamespace(
        url="https://agent.robinhood.com/mcp/trading",
        enabled_tools=[
            "get_portfolio",
            "get_equity_positions",
            "get_equity_orders",
            "get_equity_quotes",
        ],
        auth=SimpleNamespace(cache_dir="/tmp/vibe-token"),
    )

    class _Adapter:
        def __init__(self, server_name, server_config):  # noqa: ANN001
            assert server_name == "robinhood"
            assert server_config is server

        def call_tool(self, remote_name, arguments):  # noqa: ANN001
            calls.append((remote_name, dict(arguments)))
            return {"status": "ok"}

    monkeypatch.setattr("src.config.loader.load_agent_config", lambda: _agent_config(server))
    monkeypatch.setattr("src.live.registry.has_cached_oauth_token", lambda *_: True)
    monkeypatch.setattr("src.tools.mcp.MCPServerAdapter", _Adapter)

    assert service.get_account("robinhood-live-mcp")["status"] == "ok"
    assert service.get_positions("robinhood-live-mcp")["status"] == "ok"
    assert service.get_open_orders("robinhood-live-mcp")["status"] == "ok"
    assert service.get_quote("AAPL", "robinhood-live-mcp")["status"] == "ok"

    assert calls == [
        ("get_portfolio", {}),
        ("get_equity_positions", {}),
        ("get_equity_orders", {}),
        ("get_equity_quotes", {"symbols": ["AAPL"]}),
    ]
