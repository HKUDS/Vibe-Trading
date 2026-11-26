"""Swarm cancellation during a turn and by run ID after the tool returns."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import json
import threading
import time
from datetime import datetime, timezone

import pytest

import src.swarm.runtime as rt
import src.swarm.store as store_mod
import src.tools.swarm_tool as swarm_tool
from src.swarm.models import (
    RunStatus,
    SwarmAgentSpec,
    SwarmRun,
    SwarmTask,
    WorkerResult,
)
from src.tools.swarm_tool import SwarmTool



def _indexed_run_ids(rt, session_id: str) -> list[str]:
    """Read the in-process cancel index that ``cancel_indexed_run`` consults."""
    with rt._ACTIVE_RUNS_LOCK:
        return [rid for rid, (sid, _) in rt._ACTIVE_RUNS.items() if sid == session_id]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _running_run(run_id: str = "r-cancel") -> SwarmRun:
    agent = SwarmAgentSpec(
        id="analyst",
        role="Analyst",
        system_prompt="x",
        timeout_seconds=300,
    )
    task = SwarmTask(id="t1", agent_id="analyst", prompt_template="do x")
    run = SwarmRun(
        id=run_id,
        preset_name="demo",
        created_at=_iso(datetime.now(timezone.utc)),
        agents=[agent],
        tasks=[task],
    )
    run.status = RunStatus.running
    return run


@pytest.fixture(autouse=True)
def _clean_index():
    """Keep the module-level run index from leaking between tests."""
    rt._ACTIVE_RUNS.clear()
    yield
    rt._ACTIVE_RUNS.clear()


# ---------------------------------------------------------------------------
# 1. SwarmTool honours the session cancel flag
# ---------------------------------------------------------------------------


def test_execute_returns_cancelled_without_waiting_for_the_poll(tmp_path, monkeypatch):
    """A cancelled session must end the tool call, not the 5s poll interval."""
    monkeypatch.setattr(store_mod, "swarm_runs_root", lambda: tmp_path)
    monkeypatch.setattr(swarm_tool, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(swarm_tool, "_CANCEL_SETTLE_SECONDS", 1.0)

    run = _running_run()
    store = store_mod.SwarmStore(base_dir=tmp_path)
    store.create_run(run)

    cancel_calls: list[str] = []

    def fake_start_run(self, preset_name, variables, **kwargs):
        return run

    def fake_cancel_run(self, run_id):
        cancel_calls.append(run_id)
        # Mimic a worker honouring the flag at the end of its current step.
        cancelled = store.load_run(run_id)
        assert cancelled is not None
        cancelled.status = RunStatus.cancelled
        store.update_run(cancelled)
        return True

    monkeypatch.setattr(rt.SwarmRuntime, "start_run", fake_start_run)
    monkeypatch.setattr(rt.SwarmRuntime, "cancel_run", fake_cancel_run)
    monkeypatch.setattr(swarm_tool, "_resolve_preset", lambda prompt, name: ("demo", None))
    monkeypatch.setattr(swarm_tool, "_build_variables", lambda preset, prompt: ({}, None))

    stop = threading.Event()
    tool = SwarmTool(policy=ToolPolicy.from_config(get_env_config()), session_id="sess-1", cancel_event=stop)

    def cancel_soon():
        time.sleep(0.05)
        stop.set()

    threading.Thread(target=cancel_soon, daemon=True).start()

    started = time.monotonic()
    payload = json.loads(tool.execute(prompt="analyse NVDA"))
    elapsed = time.monotonic() - started

    assert payload["status"] == "cancelled", payload
    assert payload["cancelled_by_user"] is True
    assert payload["run_id"] == "r-cancel"
    assert cancel_calls == ["r-cancel"]
    # Budget is 300s+ and the poll interval is 5s in production; anything close
    # to that means the flag was not being watched.
    assert elapsed < 1.0, f"cancel took {elapsed:.2f}s"
    # A cancelled run is terminal, so it must not linger in the index.
    assert _indexed_run_ids(rt, "sess-1") == []


@pytest.mark.parametrize("finish_before_wait", [False, True])
def test_run_stays_indexed_only_while_running(tmp_path, monkeypatch, finish_before_wait):
    monkeypatch.setattr(store_mod, "swarm_runs_root", lambda: tmp_path)
    monkeypatch.setattr("src.config.load_swarm_agent_config", lambda: None)
    monkeypatch.setattr(rt, "_ensure_dotenv", lambda: None)
    monkeypatch.setattr(rt.SwarmRuntime, "_prefetch_grounding_data", lambda *_: None)
    monkeypatch.setattr(swarm_tool, "_resolve_preset", lambda prompt, name: ("demo", None))
    monkeypatch.setattr(swarm_tool, "_build_variables", lambda preset, prompt: ({}, None))

    run = _running_run("r-timeout")
    monkeypatch.setattr(rt, "build_run_from_preset", lambda *_: run)
    layer_started = threading.Event()
    finish_layer = threading.Event()
    threads = []

    def execute_layer(self, **kwargs):
        threads.append(threading.current_thread())
        layer_started.set()
        assert finish_layer.wait(timeout=10)
        return {"t1": WorkerResult(status="completed", summary="Done")}

    def wait_budget():
        assert layer_started.wait(timeout=5)
        if finish_before_wait:
            finish_layer.set()
            threads[0].join(timeout=5)
            assert not threads[0].is_alive()
        return 0

    monkeypatch.setattr(rt.SwarmRuntime, "_execute_layer", execute_layer)
    monkeypatch.setattr(swarm_tool, "_max_wait_seconds", wait_budget)

    tool = SwarmTool(policy=ToolPolicy.from_config(get_env_config()), session_id="sess-2", cancel_event=threading.Event())
    try:
        payload = json.loads(tool.execute(prompt="test local run"))
        assert payload["status"] == ("completed" if finish_before_wait else "running")
        assert payload["wait_budget_exhausted"] is True
        assert _indexed_run_ids(rt, "sess-2") == ([] if finish_before_wait else [run.id])
    finally:
        finish_layer.set()
        for thread in threads:
            thread.join(timeout=5)

    assert not threads[0].is_alive()
    saved_run = store_mod.SwarmStore(base_dir=tmp_path).load_run(run.id)
    assert saved_run is not None
    assert saved_run.status == RunStatus.completed
    assert _indexed_run_ids(rt, "sess-2") == []


# ---------------------------------------------------------------------------
# 2. The run index the session uses to reach a run it no longer polls
# ---------------------------------------------------------------------------


def test_cancel_indexed_run_reaches_a_foreign_runtime_run():
    """The HTTP endpoint holds a different SwarmRuntime; the index bridges it."""
    rt.register_active_run("r1", "sess-a", lambda: True)

    assert rt.cancel_indexed_run("r1") is True
    assert rt.cancel_indexed_run("r1") is False


# ---------------------------------------------------------------------------
# 3. Session stop acts on the turn, while explicit swarm stop acts on the run
# ---------------------------------------------------------------------------


class _FakeLoop:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


def _bare_service():
    from src.session.service import SessionService

    service = SessionService.__new__(SessionService)
    service._active_loops = {}
    service._active_tasks = {}
    service._user_cancel_requests = set()
    service._background_handles = {}
    service._shutting_down = False
    return service


def test_cancel_current_only_stops_the_current_turn():
    service = _bare_service()
    loop = _FakeLoop()
    service._active_loops["sess-1"] = loop

    assert service.cancel_current("sess-1") is True
    assert loop.cancelled is True


@pytest.mark.parametrize("has_active_turn", [False, True])
def test_cancel_current_stops_the_swarm_its_turn_started(has_active_turn):
    """Owner decision 2026-11-26: stopping a session also stops a swarm its turn left running."""
    service = _bare_service()
    if has_active_turn:
        service._active_loops["sess-2"] = _FakeLoop()
    stopped = threading.Event()

    def cancel_run():
        stopped.set()
        return True

    rt.register_active_run("detached", "sess-2", cancel_run)
    try:
        assert service.cancel_current("sess-2") is True
        assert stopped.is_set()
        assert rt.cancel_indexed_run("detached") is False  # left the index once signalled
    finally:
        rt.unregister_active_run("detached")


def test_cancel_current_leaves_other_sessions_swarms_running():
    service = _bare_service()
    stopped = threading.Event()
    rt.register_active_run("other", "sess-3", lambda: stopped.set() or True)
    try:
        assert service.cancel_current("sess-2") is False
        assert not stopped.is_set()
    finally:
        rt.unregister_active_run("other")


# ---------------------------------------------------------------------------
# 4. The shared flag wiring the loop and the tool together
# ---------------------------------------------------------------------------


def test_agent_loop_accepts_a_shared_cancel_event():
    """AgentRuntime must reuse the caller's flag, otherwise cancel() cannot reach
    the tools that were built before the loop existed."""
    import inspect

    from src.agent.runtime import AgentRuntime

    signature = inspect.signature(AgentRuntime.__init__)
    assert "cancel_event" in signature.parameters
