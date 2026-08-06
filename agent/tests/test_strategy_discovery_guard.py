"""Frozen-contract tests for ``src.strategy_discovery.guard`` — issue #969.

The phantom-tool guard (AC2) validates that every Strategy Discovery tool
referenced by prompt routing text is actually registered, and fails safe:
missing tool → empty routing block, garbage registry → never raises.

Registries here are real ``ToolRegistry`` instances populated with minimal
``BaseTool`` stubs, so any presence-check implementation (``get``,
``__contains__``, ``tool_names``) works against them.
"""

from __future__ import annotations

import json

import pytest

from src.agent.tools import BaseTool, ToolRegistry

try:
    from src.strategy_discovery import guard as sd_guard

    GUARD_AVAILABLE = True
except ImportError:
    sd_guard = None
    GUARD_AVAILABLE = False

requires_guard = pytest.mark.skipif(
    not GUARD_AVAILABLE,
    reason="waiting on sibling A: src.strategy_discovery.guard not landed yet (issue #969)",
)

EXPECTED_TOOLS = ("list_strategies", "query_strategies", "get_strategy_evidence")


class _StubTool(BaseTool):
    """Minimal registered tool carrying only a name."""

    description = "strategy discovery stub"
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, name: str) -> None:
        self.name = name

    def execute(self, **kwargs) -> str:
        return json.dumps({"status": "ok"})


def _registry_with(names) -> ToolRegistry:
    registry = ToolRegistry()
    for name in names:
        registry.register(_StubTool(name))
    return registry


@requires_guard
class TestToolNames:
    def test_strategy_discovery_tools_tuple_exact(self) -> None:
        assert tuple(sd_guard.STRATEGY_DISCOVERY_TOOLS) == EXPECTED_TOOLS


@requires_guard
class TestToolsRegistered:
    def test_all_tools_registered(self) -> None:
        assert sd_guard.tools_registered(_registry_with(EXPECTED_TOOLS)) is True
        # Extra unrelated tools must not break the registration check.
        assert (
            sd_guard.tools_registered(
                _registry_with(EXPECTED_TOOLS + ("backtest", "read_file"))
            )
            is True
        )

    def test_missing_tools_is_false(self) -> None:
        assert (
            sd_guard.tools_registered(
                _registry_with(("list_strategies", "get_strategy_evidence"))
            )
            is False
        )
        assert sd_guard.tools_registered(ToolRegistry()) is False


@requires_guard
class TestRoutingBlock:
    def test_block_present_with_all_tools(self) -> None:
        block = sd_guard.routing_block(_registry_with(EXPECTED_TOOLS))
        assert isinstance(block, str)
        assert (
            block.strip()
        ), "routing block must be non-empty when all tools are registered"
        for tool_name in EXPECTED_TOOLS:
            assert tool_name in block, f"routing block must name {tool_name}"

    def test_block_empty_when_any_tool_missing(self) -> None:
        # Fail-safe: no capability advertised that cannot be delivered.
        for missing in EXPECTED_TOOLS:
            partial = [n for n in EXPECTED_TOOLS if n != missing]
            block = sd_guard.routing_block(_registry_with(partial))
            assert (
                block == ""
            ), f"routing block must be empty when {missing} is unregistered, got {block!r}"

    def test_block_empty_on_empty_registry(self) -> None:
        assert sd_guard.routing_block(ToolRegistry()) == ""

    def test_never_raises_on_garbage_registry(self) -> None:
        # The contract pins "never raises on garbage registry (object())".
        assert sd_guard.routing_block(object()) == ""
        assert sd_guard.routing_block(None) == ""
