"""MCP exposure of the institutional-research & alternative-data tools.

Covers the four tools that reach the MCP surface by mirroring their own JSON
Schema (``get_institutional_holdings`` / ``etf_holdings`` /
``prediction_market`` / ``research_papers``) and the red-line regression that
guards *which* tools the MCP server is allowed to surface at all.

No network: the only test that actually invokes a tool swaps the mcp_server
registry for a recording fake, so nothing reaches SEC / Polymarket / arXiv.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MIRRORED_TOOL_NAMES = (
    "get_institutional_holdings",
    "etf_holdings",
    "prediction_market",
    "research_papers",
)

# Tools that mutate state (is_readonly is not True on the agent side) and were
# ALREADY exposed on the MCP surface before the institutional-research tools
# were added. They are sandbox/session writes — a backtest run, a session file
# write, a swarm launch, research-goal bookkeeping, and selecting which broker
# profile subsequent READS use — not broker order flow.
#
# This snapshot is the regression gate: adding an MCP tool that mutates
# anything outside this list must fail the suite loudly.
KNOWN_MUTATING_MCP_TOOLS = frozenset(
    {
        "add_goal_evidence",
        "backtest",
        "run_swarm",
        "start_research_goal",
        "trading_select_connection",
        "update_research_goal_status",
        "write_file",
    }
)


def _import_mcp_server():
    """Import ``agent/mcp_server.py`` without executing ``main()``.

    Returns:
        The imported mcp_server module.
    """
    agent_dir = Path(__file__).resolve().parent.parent
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    if "mcp_server" in sys.modules:
        return sys.modules["mcp_server"]
    return importlib.import_module("mcp_server")


def _mcp_tools() -> dict[str, Any]:
    """Return the registered MCP tools keyed by name (public async API)."""
    mod = _import_mcp_server()
    return {tool.name: tool for tool in asyncio.run(mod.mcp.list_tools())}


def _tool_classes() -> dict[str, Any]:
    """Return the mirrored tool classes keyed by their tool name."""
    mod = _import_mcp_server()
    return {cls.name: cls for cls in mod._mirrored_tool_classes()}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_institutional_research_tools_are_exposed_via_mcp() -> None:
    """All four institutional-research tools must reach the MCP surface."""
    registered = set(_mcp_tools())

    missing = set(MIRRORED_TOOL_NAMES) - registered
    assert not missing, (
        f"MCP server is missing institutional-research tools: {sorted(missing)}. "
        "Check _mirrored_tool_classes() in mcp_server.py."
    )


def test_mcp_tool_count_covers_the_mirrored_tools() -> None:
    """The MCP surface must not shrink below the documented 59 tools."""
    tools = _mcp_tools()

    assert len(tools) >= 59, (
        f"Expected at least 59 MCP tools (55 pre-existing + 4 mirrored), found {len(tools)}."
    )


def test_mirrored_tool_names_match_the_agent_side_registry() -> None:
    """MCP must expose these tools under their agent-side names, not aliases.

    A renamed wrapper would make the MCP call route to a tool the local
    registry does not have, which only shows up as a 'Tool not found' envelope
    at call time.
    """
    from src.tools import build_registry

    registry = build_registry()

    for name in MIRRORED_TOOL_NAMES:
        assert registry.get(name) is not None, (
            f"{name} is exposed via MCP but absent from the agent registry"
        )


# ---------------------------------------------------------------------------
# One schema, not two
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MIRRORED_TOOL_NAMES)
def test_schema_is_the_tool_class_schema(name: str) -> None:
    """The advertised MCP schema must BE the tool's own schema, not a copy that drifts."""
    tool_cls = _tool_classes()[name]
    mcp_tool = _mcp_tools()[name]

    assert mcp_tool.parameters == tool_cls.parameters, (
        f"{name}: MCP inputSchema diverged from the tool class' parameters. "
        "The MCP wrapper must read the schema from the tool class."
    )
    # to_mcp_tool() is what a client actually receives.
    assert mcp_tool.to_mcp_tool().inputSchema == tool_cls.parameters


@pytest.mark.parametrize("name", MIRRORED_TOOL_NAMES)
def test_description_is_the_tool_class_description(name: str) -> None:
    """MCP clients get the tool's own self-contained description, verbatim."""
    tool_cls = _tool_classes()[name]
    mcp_tool = _mcp_tools()[name]

    assert mcp_tool.description == tool_cls.description
    assert mcp_tool.description, f"{name} exposes an empty description to MCP clients"


@pytest.mark.parametrize("name", MIRRORED_TOOL_NAMES)
def test_schema_is_isolated_from_the_class_attribute(name: str) -> None:
    """The registered schema must be a snapshot, so MCP cannot mutate tool state."""
    tool_cls = _tool_classes()[name]
    mcp_tool = _mcp_tools()[name]

    assert mcp_tool.parameters is not tool_cls.parameters


@pytest.mark.parametrize("name", MIRRORED_TOOL_NAMES)
def test_mirrored_tools_announce_the_same_result_envelope(name: str) -> None:
    """Mirrored tools must return the same wrapped-string envelope as the hand-written ones."""
    tools = _mcp_tools()

    assert tools[name].output_schema == tools["get_fund_flow"].output_schema


# ---------------------------------------------------------------------------
# Read-only red line
# ---------------------------------------------------------------------------


def test_order_placing_tools_are_never_exposed_via_mcp() -> None:
    """Order placement / cancellation must never appear on the MCP surface."""
    from src.tools.trading_connector_tool import (
        TradingCancelOrderTool,
        TradingPlaceOrderTool,
    )

    registered = set(_mcp_tools())
    order_tools = {TradingPlaceOrderTool.name, TradingCancelOrderTool.name}

    leaked = order_tools & registered
    assert not leaked, f"Order-placing tools leaked onto the MCP surface: {sorted(leaked)}"


def test_no_unexpected_mutating_tool_is_exposed_via_mcp() -> None:
    """No tool with ``is_readonly=False`` may join the MCP surface.

    The MCP server exposes read-only or sandbox-research tools only. A handful
    of pre-existing sandbox writers are grandfathered in
    (KNOWN_MUTATING_MCP_TOOLS); anything else showing up here means a mutating
    tool was newly exposed, which is a red-line violation.
    """
    from src.tools import build_registry

    registry = build_registry()

    exposed_mutating = {
        name
        for name in _mcp_tools()
        if (tool := registry.get(name)) is not None and tool.is_readonly is not True
    }

    assert exposed_mutating <= KNOWN_MUTATING_MCP_TOOLS, (
        "Mutating tools newly exposed via MCP: "
        f"{sorted(exposed_mutating - KNOWN_MUTATING_MCP_TOOLS)}"
    )


def test_every_mirrored_tool_is_readonly() -> None:
    """The tools added through the mirroring path are all read-only."""
    for name, cls in _tool_classes().items():
        assert cls.is_readonly is True, f"{name} is not read-only and must not be mirrored"


def test_register_mirrored_tool_refuses_a_non_readonly_class(caplog) -> None:
    """The mirroring helper is a structural gate, not a convention.

    A mutating class handed to ``_register_mirrored_tool`` must be refused and
    must not end up on the MCP surface.
    """
    mod = _import_mcp_server()

    class _MutatingTool:
        name = "definitely_not_readonly_probe"
        description = "probe"
        parameters = {"type": "object", "properties": {}, "required": []}
        is_readonly = False

    with caplog.at_level("ERROR"):
        registered = mod._register_mirrored_tool(_MutatingTool)

    assert registered is False
    assert _MutatingTool.name not in _mcp_tools()
    assert any("read-only" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Call forwarding
# ---------------------------------------------------------------------------


class _RecordingRegistry:
    """Stand-in for the local tool registry that records the forwarded call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, name: str, params: dict[str, Any]) -> str:
        """Record the call and return a JSON envelope like the real registry."""
        self.calls.append((name, params))
        return '{"status": "ok"}'


def test_mirrored_call_reaches_the_registry_with_clean_params(monkeypatch) -> None:
    """An MCP call is forwarded to the agent tool, minus nulls and undeclared keys."""
    mod = _import_mcp_server()
    recorder = _RecordingRegistry()
    monkeypatch.setattr(mod, "_registry", recorder)

    tool = _mcp_tools()["prediction_market"]
    result = asyncio.run(
        tool.run(
            {
                "mode": "search",
                "query": "fed rate cut",
                "status": None,
                "not_a_declared_arg": "drop me",
            }
        )
    )

    assert recorder.calls == [
        ("prediction_market", {"mode": "search", "query": "fed rate cut"})
    ]
    assert result.content[0].text == '{"status": "ok"}'


def test_mirrored_tool_round_trips_over_a_real_mcp_session(monkeypatch) -> None:
    """A protocol-level call_tool must reach the tool and wrap the JSON envelope.

    Uses fastmcp's in-memory client transport, so this exercises the same
    request path an OpenClaw / Claude Desktop client uses — without a socket
    and without a network call (the registry is a fake).
    """
    from fastmcp import Client

    mod = _import_mcp_server()
    recorder = _RecordingRegistry()
    monkeypatch.setattr(mod, "_registry", recorder)

    async def _call() -> Any:
        async with Client(mod.mcp) as client:
            return await client.call_tool(
                "research_papers", {"mode": "search", "query": "momentum crash"}
            )

    result = asyncio.run(_call())

    assert recorder.calls == [
        ("research_papers", {"mode": "search", "query": "momentum crash"})
    ]
    assert result.content[0].text == '{"status": "ok"}'
    assert result.structured_content == {"result": '{"status": "ok"}'}


def test_one_broken_tool_module_costs_only_its_own_tool(monkeypatch, caplog) -> None:
    """A broken tool module must not take the other three down with it.

    Regression: importing all four classes in one ``from ... import`` block
    made a single SyntaxError / missing optional dependency raise out of
    ``_mirrored_tool_classes()``, so the MCP surface silently lost all four
    institutional-research tools instead of one.
    """
    mod = _import_mcp_server()

    def _explode(module_path: str):
        if module_path.endswith("research_papers_tool"):
            raise ImportError("simulated broken module")
        return importlib.import_module(module_path)

    monkeypatch.setattr(mod, "import_module", _explode)

    with caplog.at_level("ERROR"):
        surviving = {cls.name for cls in mod._mirrored_tool_classes()}

    assert surviving == {
        "get_institutional_holdings",
        "etf_holdings",
        "prediction_market",
    }, f"one broken module took down more than its own tool: survivors={sorted(surviving)}"
    assert any("research_papers_tool" in record.message for record in caplog.records)


def test_mirrored_call_params_filter() -> None:
    """The parameter filter keeps declared, non-null arguments only."""
    mod = _import_mcp_server()
    schema = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "integer"}}}

    assert mod._mirrored_call_params(schema, {"a": "x", "b": 0, "c": 1, "d": None}) == {
        "a": "x",
        "b": 0,
    }
