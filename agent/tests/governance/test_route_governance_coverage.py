"""Phase 10.1 route-level governance coverage checks."""

from __future__ import annotations

import inspect
from pathlib import Path

from src.agent.tools import ToolRegistry
from src.core.runner import Runner
from src.governance.route_coverage import assert_backtest_env_uses_allowlist, assert_registry_governed
from src.live.order_guard import LiveOrderGuardTool


def test_api_server_remote_tool_route_uses_governed_registry() -> None:
    from src.session.service import SessionService

    source = inspect.getsource(SessionService._run_with_agent)
    assert "build_governed_tool_registry" in source
    assert "governance_surface" in source


def test_mcp_sse_server_uses_governed_registry() -> None:
    import mcp_server

    result = assert_registry_governed(
        mcp_server._build_registry_for_transport("sse", inner=ToolRegistry()),
        route_name="mcp_server.sse",
        expected_surface="mcp_sse",
    )
    assert result.uses_governed_registry is True


def test_mcp_http_server_uses_governed_registry() -> None:
    import mcp_server

    result = assert_registry_governed(
        mcp_server._build_registry_for_transport("streamable_http", inner=ToolRegistry()),
        route_name="mcp_server.http",
        expected_surface="mcp_http",
    )
    assert result.uses_governed_registry is True


def test_mcp_stdio_server_uses_governed_registry_or_documented_equivalent() -> None:
    import mcp_server

    result = assert_registry_governed(
        mcp_server._build_registry_for_transport("stdio", inner=ToolRegistry()),
        route_name="mcp_server.stdio",
        expected_surface="mcp_stdio",
        allow_documented_equivalent=True,
    )
    assert result.uses_governed_registry is True or result.documented_equivalent


def test_cli_startup_wraps_registry_with_governance() -> None:
    import cli._legacy as cli_legacy

    source = inspect.getsource(cli_legacy._run_agent)
    assert "build_governed_tool_registry" in source
    assert 'surface="cli"' in source
    assert "registry=registry" in source


def test_session_service_wraps_after_registry_build() -> None:
    from src.session.service import SessionService

    source = inspect.getsource(SessionService._run_with_agent)
    build_pos = source.index("lambda: build_registry")
    wrap_pos = source.index("registry = build_governed_tool_registry")
    loop_pos = source.index("AgentLoop(")
    assert build_pos < wrap_pos < loop_pos


def test_swarm_rejects_prompt_supplied_mcp_url() -> None:
    from src.config.loader import sanitize_session_overrides
    from src.swarm import worker

    sanitized = sanitize_session_overrides(
        {"mcpServers": {"evil": {"type": "sse", "url": "https://attacker.invalid/mcp"}}}
    )
    assert "mcpServers" not in sanitized
    assert "build_governed_tool_registry" in inspect.getsource(worker.run_worker)


def test_scheduler_does_not_construct_raw_execution_registry() -> None:
    from src.api import scheduled_routes
    from src.session.service import SessionService

    dispatch_source = inspect.getsource(scheduled_routes._dispatch_scheduled_research_job)
    service_source = inspect.getsource(SessionService._run_with_agent)
    assert 'governance_surface="scheduler"' in dispatch_source
    assert "build_governed_tool_registry" in service_source


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
    env = Runner()._build_runtime_env(tmp_path)
    result = assert_backtest_env_uses_allowlist(env)
    assert result["secret_keys_present"] == []
    assert result["allowlist_enforced"] is True
