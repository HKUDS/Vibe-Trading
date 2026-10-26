"""Regression tests for #2055 — a user stop must actually stop a swarm run.

The bug had three layers, and this file pins the two backend ones:

1. ``SessionService.cancel_current`` only cancelled the ``AgentLoop``; the swarm
   the loop had started kept running.
2. ``SwarmTool.execute`` polled in a ``time.sleep`` loop, so even a cancelled
   session left the tool (and its worker threads) burning tokens until the wait
   budget ran out.

The frontend half (a stop button that calls the cancel endpoint) lives in the
web client and is covered by its own tests.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

import src.swarm.runtime as rt
import src.swarm.store as store_mod
import src.tools.swarm_tool as swarm_tool
from src.swarm.models import (
    RunStatus,
    SwarmAgentSpec,
    SwarmRun,
    SwarmTask,
)
from src.tools.swarm_tool import SwarmTool


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
    tool = SwarmTool(session_id="sess-1", cancel_event=stop)

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
    assert rt.active_run_ids("sess-1") == []


def test_execute_does_not_cancel_on_budget_exhaustion(tmp_path, monkeypatch):
    """Guard the old behaviour: a timed-out wait must leave the run alive."""
    monkeypatch.setattr(store_mod, "swarm_runs_root", lambda: tmp_path)
    monkeypatch.setattr(swarm_tool, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(swarm_tool, "_max_wait_seconds", lambda: 0)

    run = _running_run("r-timeout")
    store = store_mod.SwarmStore(base_dir=tmp_path)
    store.create_run(run)

    monkeypatch.setattr(rt.SwarmRuntime, "start_run", lambda self, p, v, **kw: run)

    def boom(self, run_id):  # pragma: no cover - must never be reached
        raise AssertionError("budget exhaustion must not cancel the run")

    monkeypatch.setattr(rt.SwarmRuntime, "cancel_run", boom)
    monkeypatch.setattr(swarm_tool, "_resolve_preset", lambda prompt, name: ("demo", None))
    monkeypatch.setattr(swarm_tool, "_build_variables", lambda preset, prompt: ({}, None))

    tool = SwarmTool(session_id="sess-2", cancel_event=threading.Event())
    payload = json.loads(tool.execute(prompt="analyse NVDA"))

    assert payload["status"] == "running"
    assert payload["wait_budget_exhausted"] is True
    # Still indexed: the user may stop it after the tool returned.
    assert rt.active_run_ids("sess-2") == ["r-timeout"]


# ---------------------------------------------------------------------------
# 2. The run index the session uses to reach a run it no longer polls
# ---------------------------------------------------------------------------


def test_cancel_runs_for_session_only_touches_its_own_runs():
    signalled: list[str] = []

    def cancel(run_id):
        signalled.append(run_id)
        return True

    rt.register_active_run("r1", "sess-a", lambda: cancel("r1"))
    rt.register_active_run("r2", "sess-b", lambda: cancel("r2"))

    assert rt.cancel_runs_for_session("sess-a") == 1
    assert signalled == ["r1"]
    # Signalled runs leave the index so a second stop is a no-op.
    assert rt.cancel_runs_for_session("sess-a") == 0
    assert rt.active_run_ids("sess-b") == ["r2"]


def test_cancel_indexed_run_reaches_a_foreign_runtime_run():
    """The HTTP endpoint holds a different SwarmRuntime; the index bridges it."""
    rt.register_active_run("r1", "sess-a", lambda: True)

    assert rt.cancel_indexed_run("r1") is True
    assert rt.cancel_indexed_run("r1") is False


# ---------------------------------------------------------------------------
# 3. SessionService.cancel_current cascades
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
    return service


def test_cancel_current_cancels_the_swarm_of_that_session(monkeypatch):
    seen: list[str] = []

    def fake_cancel_runs_for_session(session_id):
        seen.append(session_id)
        return 1

    monkeypatch.setattr(rt, "cancel_runs_for_session", fake_cancel_runs_for_session)

    service = _bare_service()
    loop = _FakeLoop()
    service._active_loops["sess-1"] = loop

    assert service.cancel_current("sess-1") is True
    assert loop.cancelled is True
    assert seen == ["sess-1"]


def test_cancel_current_stops_a_swarm_whose_turn_already_ended(monkeypatch):
    """No loop, no task — the run outlived the turn and is still cancellable."""
    monkeypatch.setattr(rt, "cancel_runs_for_session", lambda session_id: 2)

    service = _bare_service()

    assert service.cancel_current("sess-2") is True


def test_cancel_current_reports_false_when_nothing_is_running(monkeypatch):
    monkeypatch.setattr(rt, "cancel_runs_for_session", lambda session_id: 0)

    service = _bare_service()

    assert service.cancel_current("sess-3") is False


# ---------------------------------------------------------------------------
# 4. The shared flag wiring the loop and the tool together
# ---------------------------------------------------------------------------


def test_agent_loop_accepts_a_shared_cancel_event():
    """AgentLoop must reuse the caller's flag, otherwise cancel() cannot reach
    the tools that were built before the loop existed."""
    import inspect

    from src.agent.loop import AgentLoop

    signature = inspect.signature(AgentLoop.__init__)
    assert "cancel_event" in signature.parameters
