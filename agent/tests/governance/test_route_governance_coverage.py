from __future__ import annotations

import importlib
import inspect
import types
from unittest.mock import patch

from src.agent.tools import ToolRegistry
from src.governance.manifest import ToolSurface
from src.governance.runtime import GovernedToolRegistry
from src.tools import build_filtered_registry, build_registry, build_swarm_registry


def test_raw_registry_factories_remain_non_execution_helpers() -> None:
    registry = build_registry(interactive=False)
    filtered = build_filtered_registry([], include_shell_tools=False)

    assert isinstance(registry, ToolRegistry)
    assert isinstance(filtered, ToolRegistry)
    assert not isinstance(registry, GovernedToolRegistry)
    assert not isinstance(filtered, GovernedToolRegistry)


def test_swarm_worker_factory_returns_governed_registry() -> None:
    registry = build_swarm_registry(["read_file"])

    assert isinstance(registry, GovernedToolRegistry)
    assert registry.context.surface == ToolSurface.SWARM


def test_mcp_server_tool_execution_registry_is_governed() -> None:
    mcp_server = importlib.import_module("mcp_server")
    raw = ToolRegistry()

    old_registry = mcp_server._registry
    old_include_shell_tools = mcp_server._include_shell_tools
    old_surface = mcp_server._governance_surface
    try:
        mcp_server._registry = None
        mcp_server._include_shell_tools = False
        mcp_server._governance_surface = "mcp_sse"
        with patch("src.tools.build_registry", return_value=raw):
            registry = mcp_server._get_registry()
    finally:
        mcp_server._registry = old_registry
        mcp_server._include_shell_tools = old_include_shell_tools
        mcp_server._governance_surface = old_surface

    assert isinstance(registry, GovernedToolRegistry)
    assert registry.context.surface == ToolSurface.MCP_SSE


def test_session_service_agent_route_wraps_registry_after_build() -> None:
    from src.session.service import SessionService

    source = inspect.getsource(SessionService._run_with_agent)
    build_idx = source.find("build_registry(")
    govern_idx = source.find("govern_registry(")

    assert build_idx != -1
    assert govern_idx != -1
    assert govern_idx > build_idx


def test_cli_agent_route_wraps_registry_before_agent_loop() -> None:
    legacy = importlib.import_module("cli._legacy")
    captured: dict[str, object] = {}

    class _StubAgentLoop:
        def __init__(self, *, registry, llm, event_callback, max_iterations, persistent_memory) -> None:
            del llm, event_callback, max_iterations, persistent_memory
            captured["registry"] = registry
            self.memory = types.SimpleNamespace(run_dir=None)

        def cancel(self) -> None:
            captured["cancelled"] = True

        def run(self, **kwargs):
            captured["run_kwargs"] = kwargs
            return {"content": "ok"}

    with patch("src.tools.build_registry", return_value=ToolRegistry()), patch(
        "src.agent.loop.AgentLoop", _StubAgentLoop
    ), patch("src.providers.chat.ChatLLM", lambda *args, **kwargs: object()), patch(
        "src.memory.persistent.PersistentMemory",
        lambda *args, **kwargs: types.SimpleNamespace(run_dir=None),
    ), patch(
        "src.config.loader.load_agent_config", return_value=types.SimpleNamespace(mcp_servers={})
    ):
        legacy._run_agent("hello", stream_output=False, session_id="cli-session")

    registry = captured["registry"]
    assert isinstance(registry, GovernedToolRegistry)
    assert registry.context.surface == ToolSurface.CLI


def test_scheduled_research_executor_does_not_construct_raw_tool_registry() -> None:
    from src.scheduled_research.executor import ScheduledResearchExecutor

    source = inspect.getsource(ScheduledResearchExecutor)

    assert "build_registry" not in source
    assert "build_filtered_registry" not in source
    assert "registry.execute" not in source
