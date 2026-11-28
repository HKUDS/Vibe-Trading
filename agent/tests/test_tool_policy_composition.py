"""Tool policy must be supplied at each host's composition boundary."""

from dataclasses import replace

import pytest

from src.agent.tools import ToolRegistry
from src.config.accessor import get_env_config
from src.product.tool_policy import ToolPolicy
from src.providers.chat import ChatLLM
from src.session.runtime_lock import HTTP_SERVER_OWNER, release_sessions_dir
from src.session.service import SessionService
from src.swarm import runtime, node as worker
from src.swarm.models import SwarmAgentSpec, SwarmTask, WorkerResult
from src.swarm.store import SwarmStore
from src.tools import build_filtered_registry, build_registry, build_swarm_registry
from src.tools.spawn_agent_tool import child_registry


@pytest.mark.parametrize(
    ("construct", "args"),
    [
        (ToolRegistry, ()),
        (build_registry, ()),
        (build_filtered_registry, ([],)),
        (build_swarm_registry, ([],)),
        (SessionService, (None, None, None)),
        (runtime.SwarmRuntime, (None,)),
        (worker.run_node, (None, None, {}, {}, None)),
        (ChatLLM, ()),
    ],
)
def test_policy_is_required(construct, args):
    with pytest.raises(TypeError, match="policy"):
        construct(*args)


@pytest.fixture
def restricted(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBE_TRADING_DENY_TOOL_PREFIXES", "forbidden_")
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_WRITE_ROOTS", str(tmp_path))
    return ToolPolicy.from_config(get_env_config())


def test_http_service_binds_the_host_policy(monkeypatch, tmp_path, restricted):
    import api_server
    from src.api import state

    monkeypatch.setenv("ENABLE_SESSION_RUNTIME", "true")
    monkeypatch.setattr(api_server, "_session_service", None)
    monkeypatch.setattr(state, "_session_service", None)
    monkeypatch.setattr(api_server, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(api_server, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(state, "_attach_delivery_listener", lambda _: None)
    try:
        service = state._get_session_service()
        assert service.policy == restricted
        assert service._factory.policy is service.policy
    finally:
        release_sessions_dir(tmp_path / "sessions", HTTP_SERVER_OWNER)


def test_mcp_registry_snapshots_the_server_configuration(monkeypatch, restricted):
    import mcp_server

    monkeypatch.setattr(mcp_server, "_registry", None)
    monkeypatch.setattr(mcp_server, "_include_shell_tools", False)
    registry = mcp_server._get_registry()
    assert registry.policy == replace(restricted, shell_tools_enabled=False)
    monkeypatch.setenv("VIBE_TRADING_DENY_TOOL_PREFIXES", "")
    assert mcp_server._get_registry() is registry
    assert registry.check_policy("forbidden_probe", {})[0] is False


def test_swarm_runtime_forwards_the_policy_to_its_worker(monkeypatch, tmp_path, restricted):
    seen = []

    def record_worker(*, policy, **kwargs):
        seen.append(policy)
        return WorkerResult(status="completed", summary="done")

    monkeypatch.setattr(runtime, "run_node", record_worker)
    host = runtime.SwarmRuntime(store=SwarmStore(base_dir=tmp_path), policy=restricted)
    agent = SwarmAgentSpec(id="probe", role="research", system_prompt="research")
    task = SwarmTask(id="task", agent_id=agent.id, prompt_template="research")
    result = host._run_node_with_retries(agent, task, {}, {}, tmp_path, None, "run")

    assert result.status == "completed"
    assert seen[0] is restricted


def test_spawn_child_retains_the_parent_policy(tmp_path, restricted):
    parent = ToolRegistry(policy=restricted)
    child = child_registry(parent, tmp_path)
    assert child.policy is parent.policy
    assert child.check_policy("forbidden_probe", {})[0] is False
