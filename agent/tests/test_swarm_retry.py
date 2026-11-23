"""Tests for the swarm-run retry path (MCP ``retry_run`` tool + HTTP endpoint).

Retry re-launches a brand-new run with the same preset/variables as a prior
``failed`` / ``cancelled`` / stale run, leaving the original untouched. A
still-``running`` run must be refused so we never fork an active run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import mcp_server
import src.swarm.runtime as rt
from src.config.accessor import get_env_config
from src.product.tool_policy import ToolPolicy
from src.swarm.models import RunStatus, SwarmAgentSpec, SwarmRun, SwarmTask, TaskStatus
from src.swarm.store import SwarmStore
from src.swarm.task_store import TaskStore


def _make_run(run_id: str, status: RunStatus) -> SwarmRun:
    agent = SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="x", timeout_seconds=300)
    task = SwarmTask(id="t1", agent_id="analyst", prompt_template="do x")
    run = SwarmRun(
        id=run_id,
        preset_name="demo",
        created_at=datetime.now(timezone.utc).isoformat(),
        agents=[agent],
        tasks=[task],
        user_vars={"target": "AAPL.US"},
    )
    run.status = status
    return run


def test_retry_run_missing_returns_error(tmp_path, monkeypatch):
    store = SwarmStore(base_dir=tmp_path)
    monkeypatch.setattr(mcp_server, "_get_swarm_store", lambda: store)

    payload = json.loads(mcp_server.retry_run("does-not-exist"))

    assert payload["status"] == "error"
    assert "not found" in payload["error"].lower()


def test_retry_run_rejects_path_shaped_run_id(tmp_path, monkeypatch):
    store = SwarmStore(base_dir=tmp_path)
    monkeypatch.setattr(mcp_server, "_get_swarm_store", lambda: store)

    payload = json.loads(mcp_server.retry_run("../outside/victim"))

    assert payload["status"] == "error"
    assert "run_id" in payload["error"]


def test_retry_run_refuses_running_run(tmp_path, monkeypatch):
    store = SwarmStore(base_dir=tmp_path)
    run = _make_run("r-running", RunStatus.running)
    store.create_run(run)
    monkeypatch.setattr(mcp_server, "_get_swarm_store", lambda: store)

    payload = json.loads(mcp_server.retry_run("r-running"))

    assert payload["status"] == "error"
    assert "running" in payload["error"].lower()


def test_retry_run_relaunches_failed_run_with_same_preset(tmp_path, monkeypatch):
    store = SwarmStore(base_dir=tmp_path)
    original = _make_run("r-failed", RunStatus.failed)
    store.create_run(original)
    monkeypatch.setattr(mcp_server, "_get_swarm_store", lambda: store)

    captured: dict[str, object] = {}

    def fake_start_run(self, preset_name, variables, **kwargs):
        captured["preset_name"] = preset_name
        captured["variables"] = variables
        new = _make_run("r-retry", RunStatus.running)
        new.preset_name = preset_name
        self._store.create_run(new)
        TaskStore(self._store.run_dir(new.id)).save_task(
            new.tasks[0].model_copy(update={"status": TaskStatus.in_progress})
        )
        return new

    monkeypatch.setattr(rt.SwarmRuntime, "start_run", fake_start_run)

    payload = json.loads(mcp_server.retry_run("r-failed"))

    # Same preset + user_vars carried over from the original run.
    assert captured["preset_name"] == "demo"
    assert captured["variables"] == {"target": "AAPL.US"}
    # A fresh run id is returned, not the original.
    assert payload["run_id"] == "r-retry"
    assert payload["status"] == "running"


def test_retry_run_default_resume_passes_no_resume_from(tmp_path, monkeypatch):
    """Default retry stays a full re-run: no resume_from handed to the runtime."""
    store = SwarmStore(base_dir=tmp_path)
    original = _make_run("r-failed", RunStatus.failed)
    store.create_run(original)
    monkeypatch.setattr(mcp_server, "_get_swarm_store", lambda: store)

    captured: dict[str, object] = {}

    def fake_start_run(self, preset_name, variables, **kwargs):
        captured["resume_from"] = kwargs.get("resume_from")
        new = _make_run("r-retry", RunStatus.running)
        self._store.create_run(new)
        return new

    monkeypatch.setattr(rt.SwarmRuntime, "start_run", fake_start_run)

    json.loads(mcp_server.retry_run("r-failed"))

    assert captured["resume_from"] is None


def test_retry_run_resume_true_passes_reconciled_run(tmp_path, monkeypatch):
    """resume=True replays: the reconciled original run is handed to the runtime."""
    store = SwarmStore(base_dir=tmp_path)
    original = _make_run("r-failed", RunStatus.failed)
    store.create_run(original)
    monkeypatch.setattr(mcp_server, "_get_swarm_store", lambda: store)

    captured: dict[str, object] = {}

    def fake_start_run(self, preset_name, variables, **kwargs):
        captured["resume_from"] = kwargs.get("resume_from")
        new = _make_run("r-retry", RunStatus.running)
        self._store.create_run(new)
        return new

    monkeypatch.setattr(rt.SwarmRuntime, "start_run", fake_start_run)

    json.loads(mcp_server.retry_run("r-failed", resume=True))

    resume_from = captured["resume_from"]
    assert resume_from is not None
    assert resume_from.id == "r-failed"
    assert resume_from.preset_name == "demo"


def test_retry_run_resume_rejects_completed_run(tmp_path, monkeypatch):
    """resume=True is refused for a completed run (failed/cancelled only)."""
    store = SwarmStore(base_dir=tmp_path)
    original = _make_run("r-completed", RunStatus.completed)
    store.create_run(original)
    monkeypatch.setattr(mcp_server, "_get_swarm_store", lambda: store)

    payload = json.loads(mcp_server.retry_run("r-completed", resume=True))

    assert payload["status"] == "error"
    assert "failed or cancelled" in payload["error"]

    # Plain retry of a completed run stays allowed (backward compatible).
    captured: dict[str, object] = {}

    def fake_start_run(self, preset_name, variables, **kwargs):
        captured["resume_from"] = kwargs.get("resume_from")
        new = _make_run("r-retry", RunStatus.running)
        self._store.create_run(new)
        return new

    monkeypatch.setattr(rt.SwarmRuntime, "start_run", fake_start_run)

    json.loads(mcp_server.retry_run("r-completed"))
    assert captured["resume_from"] is None


def test_http_retry_route_resume_rejects_completed_run(tmp_path, monkeypatch):
    """POST /swarm/runs/{id}/retry?resume=true on a completed run -> 409."""
    import api_server
    from fastapi.testclient import TestClient

    from src.api import swarm_routes

    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))

    store = SwarmStore(base_dir=tmp_path)
    original = _make_run("r-http-done", RunStatus.completed)
    store.create_run(original)

    monkeypatch.setattr(swarm_routes, "_get_swarm_runtime", lambda: type("R", (), {"_store": store})())
    monkeypatch.setattr(
        api_server, "_shell_tools_enabled_for_request", lambda request, **kwargs: False
    )

    resp = client.post("/swarm/runs/r-http-done/retry?resume=true")
    assert resp.status_code == 409
    assert "failed or cancelled" in resp.json()["detail"]


def test_http_retry_route_resume_query_plumbs_resume_from(tmp_path, monkeypatch):
    """POST /swarm/runs/{id}/retry?resume=true hands the reconciled run to
    start_run as resume_from; without the query it stays a full re-run."""
    import api_server
    from fastapi.testclient import TestClient

    from src.api import swarm_routes

    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))

    store = SwarmStore(base_dir=tmp_path)
    original = _make_run("r-http", RunStatus.failed)
    store.create_run(original)

    captured: dict[str, object] = {}
    call_count = 0

    class _FakeRuntime:
        _store = store
        policy = ToolPolicy.from_config(get_env_config())

        def start_run(self, preset_name, variables, **kwargs):
            nonlocal call_count
            call_count += 1
            captured["resume_from"] = kwargs.get("resume_from")
            new = _make_run(f"r-http-retry{call_count}", RunStatus.running)
            self._store.create_run(new)
            return new

    monkeypatch.setattr(swarm_routes, "_get_swarm_runtime", lambda: _FakeRuntime())
    monkeypatch.setattr(
        api_server, "_shell_tools_enabled_for_request", lambda request, **kwargs: False
    )

    resp = client.post("/swarm/runs/r-http/retry?resume=true")
    assert resp.status_code == 200
    resume_from = captured["resume_from"]
    assert resume_from is not None
    assert resume_from.id == "r-http"

    resp = client.post("/swarm/runs/r-http/retry")
    assert resp.status_code == 200
    assert captured["resume_from"] is None
