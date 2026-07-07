"""Route-level governance coverage for real entrypoint construction paths."""

from __future__ import annotations

import inspect
from pathlib import Path

from src.agent.tools import ToolRegistry
from src.core.runner import Runner
from src.governance.route_coverage import (
    assert_backtest_env_uses_allowlist,
    assert_registry_governed,
    build_governed_tool_registry,
)
from src.governance.runtime import GovernedToolRegistry
from src.live.order_guard import LiveOrderGuardTool


def test_api_server_remote_tool_route_uses_governed_registry() -> None:
    from src.session.service import SessionService

    source = inspect.getsource(SessionService._run_with_agent)
    assert "build_governed_tool_registry" in source
    assert "governance_surface" in source

    governed = build_governed_tool_registry(ToolRegistry(), surface="remote_api")
    result = assert_registry_governed(
        governed,
        route_name="api_server.remote_tool_execution",
        expected_surface="remote_api",
    )

    assert result.uses_governed_registry is True


def test_mcp_sse_server_uses_governed_registry() -> None:
    import mcp_server

    governed = mcp_server._build_registry_for_transport("sse", inner=ToolRegistry())
    result = assert_registry_governed(
        governed,
        route_name="mcp_server.sse",
        expected_surface="mcp_sse",
    )

    assert result.uses_governed_registry is True


def test_mcp_http_server_uses_governed_registry() -> None:
    import mcp_server

    governed = mcp_server._build_registry_for_transport("streamable_http", inner=ToolRegistry())
    result = assert_registry_governed(
        governed,
        route_name="mcp_server.http",
        expected_surface="mcp_http",
    )

    assert result.uses_governed_registry is True


def test_mcp_stdio_server_uses_governed_registry_or_documented_equivalent() -> None:
    import mcp_server

    governed = mcp_server._build_registry_for_transport("stdio", inner=ToolRegistry())
    result = assert_registry_governed(
        governed,
        route_name="mcp_server.stdio",
        expected_surface="mcp_stdio",
        allow_documented_equivalent=True,
    )

    assert result.uses_governed_registry is True or result.documented_equivalent


def test_swarm_worker_registry_rejects_prompt_mcp_url() -> None:
    from src.config.loader import sanitize_session_overrides
    from src.swarm import worker

    source = inspect.getsource(worker.run_worker)
    assert "build_governed_tool_registry" in source
    assert "surface=\"swarm\"" in source

    sanitized = sanitize_session_overrides(
        {"mcpServers": {"evil": {"type": "sse", "url": "https://attacker.invalid/mcp"}}}
    )
    assert "mcpServers" not in sanitized


def test_scheduler_executor_uses_scheduler_runtime_context() -> None:
    from src.api import scheduled_routes
    from src.session.service import SessionService

    dispatch_source = inspect.getsource(scheduled_routes._dispatch_scheduled_research_job)
    service_source = inspect.getsource(SessionService._run_with_agent)

    assert 'governance_surface="scheduler"' in dispatch_source
    assert "build_governed_tool_registry" in service_source
    assert "governance_surface" in service_source


def test_live_runtime_scheduler_cannot_bypass_live_guard() -> None:
    from src.live import registry as live_registry
    from src.live.runtime import runner as live_runner

    registry_source = inspect.getsource(live_registry.wrap_live_broker_tools)
    runner_source = inspect.getsource(live_runner.LiveRunner.run_once)

    assert "LiveOrderGuardTool" in registry_source
    assert "ToolClass.UNKNOWN" in registry_source
    assert issubclass(LiveOrderGuardTool, object)
    assert "_load_mandate" in runner_source
    assert "_halt_flag" in runner_source
    assert "_run_reconcile" in runner_source


def test_backtest_subprocess_env_builder_uses_allowlist(tmp_path: Path) -> None:
    runner = Runner()
    env = runner._build_runtime_env(tmp_path)
    result = assert_backtest_env_uses_allowlist(env)

    assert result["secret_keys_present"] == []
    assert result["allowlist_enforced"] is True
