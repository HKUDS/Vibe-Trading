"""Integration tests for MCP tool injection into the tool registry (Phase 3)."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mcp import types as mcp_types
from fastmcp.client.client import CallToolResult

from src.agent.tools import BaseTool
from src.config.schema import AgentConfig, MCPServerConfig
from src.tools import build_registry
from src.tools.mcp import MCPRemoteTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server_config(**overrides: Any) -> MCPServerConfig:
    """Create a minimal valid stdio MCPServerConfig."""
    payload: dict[str, Any] = {
        "command": "uvx",
        "args": ["demo-server"],
        "enabled_tools": ["*"],
        "tool_timeout": 5,
    }
    payload.update(overrides)
    return MCPServerConfig.model_validate(payload)


def _make_agent_config(servers: dict[str, dict[str, Any]]) -> AgentConfig:
    """Build an AgentConfig from a plain server-name → config-dict map."""
    return AgentConfig.model_validate(
        {"mcpServers": {name: cfg for name, cfg in servers.items()}}
    )


def _fake_tool(name: str) -> mcp_types.Tool:
    """Construct a minimal fake MCP tool definition."""
    return mcp_types.Tool(
        name=name,
        description=f"Fake tool {name}",
        inputSchema={"type": "object", "properties": {}, "required": []},
    )


def _make_fake_wrappers(server_name: str, tool_names: list[str]) -> list[MCPRemoteTool]:
    """Build lightweight MCPRemoteTool stubs without a live adapter."""
    adapter = MagicMock()
    adapter.server_name = server_name
    wrappers = []
    for tname in tool_names:
        stub = MagicMock(spec=MCPRemoteTool)
        stub.name = f"mcp_{server_name}_{tname}"
        stub.description = f"Remote {tname}"
        stub.parameters = {"type": "object", "properties": {}, "required": []}
        stub.is_readonly = False
        wrappers.append(stub)
    return wrappers  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Regression: no agent_config → unchanged behaviour
# ---------------------------------------------------------------------------


def test_no_agent_config_produces_no_mcp_tools() -> None:
    """build_registry() with no agent_config must not add any mcp_ tools."""
    registry = build_registry()

    mcp_names = [n for n in registry.tool_names if n.startswith("mcp_")]
    assert mcp_names == [], f"Unexpected MCP tools in registry: {mcp_names}"


def test_empty_mcp_servers_produces_no_mcp_tools() -> None:
    """An AgentConfig with no mcp_servers must behave like no config at all."""
    empty_config = AgentConfig.model_validate({"mcpServers": {}})
    registry = build_registry(agent_config=empty_config)

    mcp_names = [n for n in registry.tool_names if n.startswith("mcp_")]
    assert mcp_names == [], f"Unexpected MCP tools in registry: {mcp_names}"


# ---------------------------------------------------------------------------
# Happy path: MCP tools appear after local tools
# ---------------------------------------------------------------------------


def test_mcp_tools_are_injected_and_come_after_local_tools() -> None:
    """MCP tools must be appended after local tools, preserving local order."""
    fake_wrappers = _make_fake_wrappers("demo", ["price_quote", "search"])

    with patch("src.tools.mcp.build_mcp_tool_wrappers", return_value=fake_wrappers):
        config = _make_agent_config({"demo": {"command": "uvx", "args": []}})
        registry = build_registry(agent_config=config)

    all_names = registry.tool_names
    mcp_names = [n for n in all_names if n.startswith("mcp_")]
    local_names = [n for n in all_names if not n.startswith("mcp_")]

    assert "mcp_demo_price_quote" in mcp_names
    assert "mcp_demo_search" in mcp_names

    # Every local tool must appear before every MCP tool in the ordered list.
    if local_names and mcp_names:
        last_local_idx = max(all_names.index(n) for n in local_names)
        first_mcp_idx = min(all_names.index(n) for n in mcp_names)
        assert last_local_idx < first_mcp_idx, (
            "MCP tools must come after all local tools in the registry"
        )


def test_mcp_tools_registration_order_matches_config_order() -> None:
    """Tools from the same server are registered in discovery order."""
    fake_wrappers = _make_fake_wrappers("alpha", ["tool_a", "tool_b", "tool_c"])

    with patch("src.tools.mcp.build_mcp_tool_wrappers", return_value=fake_wrappers):
        config = _make_agent_config({"alpha": {"command": "uvx", "args": []}})
        registry = build_registry(agent_config=config)

    mcp_names = [n for n in registry.tool_names if n.startswith("mcp_alpha_")]
    assert mcp_names == ["mcp_alpha_tool_a", "mcp_alpha_tool_b", "mcp_alpha_tool_c"]


# ---------------------------------------------------------------------------
# is_readonly enforcement
# ---------------------------------------------------------------------------


def test_mcp_tools_are_not_readonly() -> None:
    """All MCP tools injected into the registry must have is_readonly=False."""
    fake_wrappers = _make_fake_wrappers("srv", ["query"])

    with patch("src.tools.mcp.build_mcp_tool_wrappers", return_value=fake_wrappers):
        config = _make_agent_config({"srv": {"command": "uvx", "args": []}})
        registry = build_registry(agent_config=config)

    mcp_tools = [registry.get(n) for n in registry.tool_names if n.startswith("mcp_")]
    assert mcp_tools, "Expected at least one MCP tool to be registered"
    for tool in mcp_tools:
        assert tool is not None
        assert tool.is_readonly is False, (
            f"Tool {tool.name} must have is_readonly=False to stay on the serial path"
        )


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


def test_failed_mcp_server_does_not_block_local_tools(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A server that raises during discovery must be skipped with a warning."""
    with patch(
        "src.tools.mcp.build_mcp_tool_wrappers",
        side_effect=RuntimeError("connection refused"),
    ):
        config = _make_agent_config({"broken": {"command": "uvx", "args": []}})
        with caplog.at_level(logging.WARNING, logger="src.tools"):
            registry = build_registry(agent_config=config)

    # Local tools must still be present.
    assert len(registry) > 0

    # No MCP tools should appear.
    mcp_names = [n for n in registry.tool_names if n.startswith("mcp_")]
    assert mcp_names == []

    # A warning must be emitted naming the skipped server.
    assert any("broken" in record.message for record in caplog.records), (
        "Expected a warning mentioning the skipped server name"
    )


def test_one_failed_server_does_not_affect_other_mcp_servers() -> None:
    """Tools from a healthy server must be registered even if another server fails."""
    good_wrappers = _make_fake_wrappers("good", ["alpha"])

    def _selective_factory(server_name: str, server_config: MCPServerConfig, **_kw: Any):
        if server_name == "broken":
            raise RuntimeError("refused")
        return good_wrappers

    with patch("src.tools.mcp.build_mcp_tool_wrappers", side_effect=_selective_factory):
        config = _make_agent_config({
            "broken": {"command": "uvx", "args": []},
            "good": {"command": "uvx", "args": []},
        })
        registry = build_registry(agent_config=config)

    assert "mcp_good_alpha" in registry.tool_names
    broken_tools = [n for n in registry.tool_names if n.startswith("mcp_broken_")]
    assert broken_tools == []


# ---------------------------------------------------------------------------
# No-config regression: existing call sites unaffected
# ---------------------------------------------------------------------------


def test_build_registry_default_call_is_unchanged() -> None:
    """Calling build_registry() with no kwargs must produce identical results."""
    r1 = build_registry()
    r2 = build_registry(agent_config=None)

    assert set(r1.tool_names) == set(r2.tool_names)
