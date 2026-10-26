"""A session cancel must reach an in-flight swarm run started by SwarmTool.

Stopping a chat turn used to cancel only the AgentLoop. The SwarmTool call
kept polling its run for up to SWARM_TIMEOUT, and the run itself was never
signalled. The cancel signal is now shared with the tool, and the run
registry is process-wide so cancel_run() works from any SwarmRuntime
instance.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import src.swarm.runtime as runtime_mod
from src.agent.loop import AgentLoop
from src.agent.tools import ToolRegistry
from src.swarm.runtime import SwarmRuntime
from src.tools.swarm_tool import SwarmTool


def _run_with_status(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        status=SimpleNamespace(value=status),
        id="run-1",
        tasks=[],
        final_report="",
        total_input_tokens=0,
        total_output_tokens=0,
        token_source="",
        agents=[],
        tokens_used=0,
    )


def test_wait_for_poll_returns_true_once_cancel_is_set() -> None:
    cancel = threading.Event()
    tool = SwarmTool(cancel_event=cancel)
    cancel.set()

    assert tool._wait_for_poll() is True


def test_wait_for_poll_without_cancel_event_sleeps_and_returns_false(
    monkeypatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr("src.tools.swarm_tool.time.sleep", lambda s: slept.append(s))
    tool = SwarmTool()

    assert tool._wait_for_poll() is False
    assert slept == [5]


def test_cancel_and_report_signals_run_and_returns_cancelled(monkeypatch) -> None:
    monkeypatch.setattr("src.tools.swarm_tool._CANCEL_GRACE_SECONDS", 2)
    runtime = MagicMock()
    runtime.cancel_run.return_value = True
    store = MagicMock()
    store.load_run.return_value = object()
    store.reconcile_run.return_value = _run_with_status("cancelled")

    tool = SwarmTool(cancel_event=threading.Event())
    result = json.loads(
        tool._cancel_and_report(runtime, store, "run-1", "investment_committee", {})
    )

    runtime.cancel_run.assert_called_once_with("run-1")
    assert result["status"] == "cancelled"
    assert result["run_id"] == "run-1"


def test_cancel_and_report_reports_cancelling_when_run_outlives_grace(
    monkeypatch,
) -> None:
    monkeypatch.setattr("src.tools.swarm_tool._CANCEL_GRACE_SECONDS", 0)
    runtime = MagicMock()
    runtime.cancel_run.return_value = True
    store = MagicMock()
    store.load_run.return_value = object()
    store.reconcile_run.return_value = _run_with_status("running")

    tool = SwarmTool(cancel_event=threading.Event())
    result = json.loads(
        tool._cancel_and_report(runtime, store, "run-1", "investment_committee", {})
    )

    assert result["status"] == "cancelling"
    assert result["run_id"] == "run-1"
    assert "still stopping" in result["error"]


def test_cancel_run_finds_run_registered_by_another_instance() -> None:
    store = MagicMock()
    owner = SwarmRuntime(store=store, max_workers=1, agent_config=None)
    caller = SwarmRuntime(store=store, max_workers=1, agent_config=None)
    event = threading.Event()
    runtime_mod._ACTIVE_CANCEL_EVENTS["run-shared"] = event
    try:
        assert caller.cancel_run("run-shared") is True
        assert event.is_set()
        assert owner.cancel_run("missing-run") is False
    finally:
        runtime_mod._ACTIVE_CANCEL_EVENTS.pop("run-shared", None)


def test_agent_loop_cancel_sets_shared_event() -> None:
    shared = threading.Event()
    loop = AgentLoop(registry=ToolRegistry(), llm=MagicMock(), cancel_event=shared)

    loop.cancel()

    assert shared.is_set()
