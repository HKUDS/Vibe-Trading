"""Regression: cancel_run() must stop an already-dispatched worker promptly,
not just skip layers that have not started yet.

Pre-fix: cancel_event was threaded from cancel_run() into _execute_run and
_execute_layer, and polled between layers, but was never passed into
_run_node_with_retries or run_node. A worker already running when
cancel_run() fired ran to completion untouched, exactly the gap AgentRuntime's
should_cancel mechanism (agent/src/agent/loop.py) already closed for the
main, non-swarm agent loop.

Post-fix: cancel_event reaches run_node(), is passed to
ChatLLM.stream_chat() as should_cancel (interrupting an in-flight LLM
stream), and is checked at the top of each ReAct iteration and right after
the stream returns, mirroring AgentRuntime's cooperative-cancellation
contract: an in-flight stream stops promptly and that turn's tool calls
are skipped, but a tool call already executing is not interrupted.
"""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import threading
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path

import pytest

import src.swarm.runtime as rt
from src.swarm.models import RunStatus, SwarmAgentSpec, SwarmRun, SwarmTask, TaskStatus, WorkerResult
from src.swarm.store import SwarmStore
from src.swarm.task_store import TaskStore


def _make_run(tmp_path: Path):
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(policy=ToolPolicy.from_config(get_env_config()), store=store)
    agents = [SwarmAgentSpec(id="a", role="x", system_prompt="x", max_retries=0)]
    tasks = [SwarmTask(id="t1", agent_id="a", prompt_template="do x")]
    run = SwarmRun(
        id="r-cancel",
        preset_name="demo",
        created_at="2026-05-27T18:30:56+00:00",
        agents=agents,
        tasks=tasks,
    )
    store.create_run(run)
    return store, runtime, run


def test_cancel_mid_flight_worker_stops_promptly(tmp_path, monkeypatch):
    def slow_worker(agent_spec, task, **kwargs):
        cancel_event = kwargs.get("cancel_event")
        for _ in range(150):
            if cancel_event is not None and cancel_event.is_set():
                return WorkerResult(status="cancelled", summary="cancelled")
            time.sleep(0.01)
        return WorkerResult(status="completed", summary="done")

    monkeypatch.setattr(rt, "run_node", slow_worker)
    store, runtime, run = _make_run(tmp_path)
    cancel_event = threading.Event()

    def _cancel_soon():
        time.sleep(0.1)
        cancel_event.set()

    threading.Thread(target=_cancel_soon).start()
    t0 = time.monotonic()
    runtime._execute_run(run, cancel_event)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.5, (
        f"cancel_run() did not reach the in-flight worker promptly: run took "
        f"{elapsed:.2f}s despite cancel_event being set after 0.1s."
    )


def test_run_node_receives_cancel_event_kwarg(tmp_path, monkeypatch):
    """The retry wrapper must actually forward cancel_event to run_node,
    not just accept it."""
    received = {}

    def capture_worker(agent_spec, task, **kwargs):
        received["cancel_event"] = kwargs.get("cancel_event")
        return WorkerResult(status="completed", summary="done")

    monkeypatch.setattr(rt, "run_node", capture_worker)
    store, runtime, run = _make_run(tmp_path)
    cancel_event = threading.Event()

    runtime._execute_run(run, cancel_event)

    worker_stop = received["cancel_event"]
    assert not worker_stop.is_set()
    cancel_event.set()
    assert worker_stop.wait(0)


def test_cancelled_worker_result_persists_as_cancelled_task(tmp_path, monkeypatch):
    """A worker that stopped because cancel_run() fired must land as a
    *cancelled* task with a task_cancelled event — the generic "worker did
    not complete" branch would otherwise relabel a user stop as a failure."""
    def cancelling_worker(agent_spec, task, **kwargs):
        cancel_event.set()
        assert kwargs["cancel_event"].is_set()
        return WorkerResult(status="cancelled", summary="stopped on request", iterations=2)

    monkeypatch.setattr(rt, "run_node", cancelling_worker)
    store, runtime, run = _make_run(tmp_path)
    cancel_event = threading.Event()

    runtime._execute_run(run, cancel_event)

    task = TaskStore(store.run_dir(run.id)).load_task("t1")
    assert task.status == TaskStatus.cancelled, task.status
    assert not task.error, f"a cancelled task must carry no failure error, got {task.error!r}"
    assert task.worker_iterations == 2

    event_types = [e.type for e in store.read_events(run.id)]
    assert "task_cancelled" in event_types, event_types
    assert "task_failed" not in event_types, event_types

    assert store.load_run(run.id).status == RunStatus.cancelled


def test_cancel_run_wakes_worker_retry_wait(tmp_path, monkeypatch):
    store, runtime, run = _make_run(tmp_path)
    run.agents[0].max_retries = 1
    waiting = threading.Event()
    attempts = []

    class ObservedEvent(threading.Event):
        def wait(self, timeout=None):
            waiting.set()
            return super().wait(timeout)

    def worker(agent_spec, task, **kwargs):
        attempts.append(task.id)
        return WorkerResult(status="failed", summary="partial", input_tokens=7)

    parent = ObservedEvent()
    runtime._cancel_events[run.id] = parent
    monkeypatch.setattr(rt, "run_node", worker)
    monkeypatch.setattr(rt, "_worker_retry_delay_s", lambda attempt: 3.0)
    thread = threading.Thread(target=runtime._execute_run, args=(run, parent))
    thread.start()
    try:
        assert waiting.wait(5), "worker did not enter retry wait"
        assert runtime.cancel_run(run.id)
    finally:
        parent.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert attempts == ["t1"]
    persisted = store.load_run(run.id)
    assert persisted.status == RunStatus.cancelled
    assert persisted.total_input_tokens == 7
    assert TaskStore(store.run_dir(run.id)).load_task("t1").summary == "partial"


def test_layer_deadline_stops_worker_without_cancelling_the_run(tmp_path, monkeypatch):
    from src.swarm.node import UsageMeasure

    store, runtime, run = _make_run(tmp_path)
    run.agents[0].max_retries = 1
    run.tasks.extend([
        SwarmTask(id="sibling", agent_id="a", prompt_template="finish first"),
        SwarmTask(id="next", agent_id="a", prompt_template="use partial work", depends_on=["t1"]),
    ])
    parent = threading.Event()
    waiting_to_append = threading.Event()
    release = threading.Event()
    attempts = []
    signals = {}
    overdue_futures = []
    original_lock = store._write_lock
    real_as_completed = rt.as_completed
    overdue_thread = None

    class DelayedAppendLock:
        def __enter__(self):
            if threading.current_thread() is overdue_thread and not release.is_set():
                waiting_to_append.set()
                assert release.wait(5), "fixture did not release the delayed append"
            original_lock.acquire()

        def __exit__(self, *exc):
            original_lock.release()

    def worker(agent_spec, task, *, cancel_event, event_callback, record_usage, **kwargs):
        nonlocal overdue_thread
        attempts.append(task.id)
        if task.id == "t1":
            overdue_thread = threading.current_thread()
            event_callback(runtime._make_event("worker_text", task_id=task.id))
            signals[task.id] = cancel_event.is_set()
            record_usage(UsageMeasure(101, 23, 0, 0, "provider"), {"input_tokens": 101, "output_tokens": 23})
            return WorkerResult(status="failed", summary="late fixture")
        signals[task.id] = cancel_event.is_set()
        return WorkerResult(status="completed", summary=task.id)

    def expire_first_layer(futures, timeout=None):
        if len(futures) == 2:
            assert waiting_to_append.wait(5), "fixture did not start the delayed append"
            complete = next(real_as_completed(futures, timeout=5))
            overdue_futures.append(next(future for future in futures if future is not complete))
            yield complete
            raise FuturesTimeoutError
        yield from real_as_completed(futures, timeout=timeout)

    monkeypatch.setattr(store, "_write_lock", DelayedAppendLock())
    monkeypatch.setattr(rt, "run_node", worker)
    monkeypatch.setattr(rt, "as_completed", expire_first_layer)
    monkeypatch.setattr(rt, "_worker_retry_delay_s", lambda attempt: 0.0)

    try:
        runtime._execute_run(run, parent)
        before = store.read_events(run.id)
        assert before[-1].type == "run_completed"
    finally:
        release.set()
        if overdue_futures:
            overdue_futures[0].result(timeout=5)

    tasks = TaskStore(store.run_dir(run.id))
    expired_task = tasks.load_task("t1")
    assert expired_task.status == TaskStatus.failed
    assert "exceeded layer deadline" in expired_task.error
    assert "outcome is unknown" in expired_task.error
    assert "before retrying" in expired_task.error
    assert tasks.load_task("sibling").status == TaskStatus.completed
    assert tasks.load_task("next").status == TaskStatus.completed
    persisted = store.load_run(run.id)
    assert persisted.status == RunStatus.failed
    assert (persisted.total_input_tokens, persisted.total_output_tokens, persisted.token_source) == (101, 23, "provider")
    assert not parent.is_set() and not signals["next"]
    assert signals["t1"]
    assert attempts.count("t1") == 1
    assert store.read_events(run.id) == before

    resumed = run.model_copy(update={"id": "r-resume", "status": RunStatus.pending})
    monkeypatch.setattr(rt, "build_run_from_preset", lambda *_: resumed)
    monkeypatch.setattr(threading.Thread, "start", lambda _: None)
    with pytest.raises(ValueError, match="outcome is unknown"):
        runtime.start_run(run.preset_name, {}, resume_from=persisted)
    assert not store.run_dir(resumed.id).exists()


def test_cli_cancels_active_run_owned_by_another_process(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    store, runtime, run = _make_run(tmp_path)
    monkeypatch.setattr(rt, "build_run_from_preset", lambda *_: run)
    entered = threading.Event()
    exited = threading.Event()
    real_execute_run = runtime._execute_run

    def worker(**kwargs):
        entered.set()
        stopped = kwargs["cancel_event"].wait(10)
        return WorkerResult(status="cancelled" if stopped else "completed", summary="")

    def execute_run(*args):
        try:
            real_execute_run(*args)
        finally:
            exited.set()

    monkeypatch.setattr(rt, "run_node", worker)
    monkeypatch.setattr(runtime, "_execute_run", execute_run)
    # start_run owns record creation.
    run.id = "r-cli-cancel"
    runtime.start_run("demo", {})
    try:
        assert entered.wait(5)
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import sys; from pathlib import Path; "
                "from cli.commands import common, swarm_runtime; "
                "common.SWARM_DIR = Path(sys.argv[1]); "
                "sys.exit(swarm_runtime.cmd_swarm_cancel(sys.argv[2]))",
                str(store.base_dir), run.id,
            ],
            env={**os.environ, "PYTHONPATH": str(Path(rt.__file__).resolve().parents[2])},
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert exited.wait(5)
        assert store.load_run(run.id).status == RunStatus.cancelled
        assert not store.request_cancel(run.id)
    finally:
        runtime.cancel_run(run.id)
        assert exited.wait(5)


def test_mcp_cancel_swarm_requests_cancellation_by_run_id(tmp_path, monkeypatch):
    import asyncio
    import json

    import mcp_server
    from fastmcp import Client

    store, _, run = _make_run(tmp_path)
    monkeypatch.setattr(mcp_server, "_get_swarm_store", lambda: store)

    async def request():
        async with Client(mcp_server.mcp) as client:
            accepted = await client.call_tool("cancel_swarm", {"run_id": run.id})
            missing = await client.call_tool("cancel_swarm", {"run_id": "missing"})
            return json.loads(accepted.content[0].text), json.loads(missing.content[0].text)

    accepted, missing = asyncio.run(request())
    assert accepted == {"status": "cancel_requested", "run_id": run.id}
    assert missing["status"] == "error"
    assert (store.run_dir(run.id) / "cancel.request").is_file()


def test_cancel_by_id_rejects_an_unreadable_run_record(tmp_path, monkeypatch, capsys):
    import asyncio
    import json

    import mcp_server
    from cli.commands import common, swarm_runtime
    from fastmcp import Client

    store, _, run = _make_run(tmp_path)
    run_dir = store.run_dir(run.id)
    (run_dir / "run.json").write_text('{"status":"private-invalid-value"}')
    monkeypatch.setattr(mcp_server, "_get_swarm_store", lambda: store)
    monkeypatch.setattr(common, "SWARM_DIR", store.base_dir)

    async def request():
        async with Client(mcp_server.mcp) as client:
            result = await client.call_tool("cancel_swarm", {"run_id": run.id})
            return json.loads(result.content[0].text)

    assert asyncio.run(request()) == {"status": "error", "error": "Invalid swarm run record"}
    assert swarm_runtime.cmd_swarm_cancel(run.id) == 1
    assert "Invalid swarm run record" in capsys.readouterr().out
    assert not (run_dir / "cancel.request").exists()


def test_layer_deadline_retains_partial_research_and_blocks_overlapping_resume(tmp_path, monkeypatch):
    from src.session.thread import ThreadLog
    from src.swarm.artifacts import node_thread

    store, runtime, run = _make_run(tmp_path)
    root = store.run_dir(run.id)
    partial = "PARTIAL_RESEARCH: revenue grew 12% year over year; margins are still being checked. " * 2
    entered, release = threading.Event(), threading.Event()
    real_as_completed = rt.as_completed
    pending = []

    def worker(agent_spec, task, *, cancel_event, **kwargs):
        log = ThreadLog(node_thread(root, agent_spec.id, task.id))
        log.append("user", "turn-1", content="do x", llm_content="do x")
        log.append("assistant", "turn-1", content=partial, phase="commentary")
        entered.set()
        release.wait(5)
        return WorkerResult(status="cancelled", summary="settled late")

    def expire(futures, timeout=None):
        assert entered.wait(5)
        pending.extend(futures)
        raise FuturesTimeoutError
        yield  # pragma: no cover - makes this a generator like as_completed

    monkeypatch.setattr(rt, "run_node", worker)
    monkeypatch.setattr(rt, "as_completed", expire)
    monkeypatch.setattr(runtime, "_prefetch_grounding_data", lambda run: None)
    try:
        runtime._execute_run(run, threading.Event())
    finally:
        release.set()
        for future in pending:
            future.result(timeout=5)
        monkeypatch.setattr(rt, "as_completed", real_as_completed)

    saved = store.load_run(run.id)
    task = saved.tasks[0]
    assert saved.status == RunStatus.failed
    assert task.status == TaskStatus.failed
    assert "exceeded layer deadline" in task.error and "outcome is unknown" in task.error
    assert task.summary == partial
    assert saved.report_is_partial
    assert "PARTIAL_RESEARCH" in saved.final_report

    resumed = run.model_copy(update={"id": "r-resume-partial", "status": RunStatus.pending})
    monkeypatch.setattr(rt, "build_run_from_preset", lambda *_: resumed)
    monkeypatch.setattr(threading.Thread, "start", lambda _: None)
    with pytest.raises(ValueError, match="outcome is unknown"):
        runtime.start_run(run.preset_name, {}, resume_from=saved)
