"""Regression: cancel_run() must stop an already-dispatched worker promptly,
not just skip layers that have not started yet.

Pre-fix: cancel_event was threaded from cancel_run() into _execute_run and
_execute_layer, and polled between layers, but was never passed into
_run_worker_with_retries or run_worker. A worker already running when
cancel_run() fired ran to completion untouched, exactly the gap AgentLoop's
should_cancel mechanism (agent/src/agent/loop.py) already closed for the
main, non-swarm agent loop.

Post-fix: cancel_event reaches run_worker(), is passed to
ChatLLM.stream_chat() as should_cancel (interrupting an in-flight LLM
stream), and is checked at the top of each ReAct iteration and right after
the stream returns, mirroring AgentLoop's cooperative-cancellation
contract: an in-flight stream stops promptly and that turn's tool calls
are skipped, but a tool call already executing is not interrupted.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path

import src.swarm.runtime as rt
from src.swarm.models import RunStatus, SwarmAgentSpec, SwarmRun, SwarmTask, TaskStatus, WorkerResult
from src.swarm.store import SwarmStore
from src.swarm.task_store import TaskStore


def _make_run(tmp_path: Path):
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
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

    monkeypatch.setattr(rt, "run_worker", slow_worker)
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


def test_run_worker_receives_cancel_event_kwarg(tmp_path, monkeypatch):
    """The retry wrapper must actually forward cancel_event to run_worker,
    not just accept it."""
    received = {}

    def capture_worker(agent_spec, task, **kwargs):
        received["cancel_event"] = kwargs.get("cancel_event")
        return WorkerResult(status="completed", summary="done")

    monkeypatch.setattr(rt, "run_worker", capture_worker)
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

    monkeypatch.setattr(rt, "run_worker", cancelling_worker)
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
    monkeypatch.setattr(rt, "run_worker", worker)
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

    def worker(agent_spec, task, *, cancel_event, event_callback, **kwargs):
        nonlocal overdue_thread
        attempts.append(task.id)
        if task.id == "t1":
            overdue_thread = threading.current_thread()
            event_callback(runtime._make_event("worker_text", task_id=task.id))
            signals[task.id] = cancel_event.is_set()
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
    monkeypatch.setattr(rt, "run_worker", worker)
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
    assert tasks.load_task("sibling").status == TaskStatus.completed
    assert tasks.load_task("next").status == TaskStatus.completed
    assert store.load_run(run.id).status == RunStatus.failed
    assert not parent.is_set() and not signals["next"]
    assert signals["t1"]
    assert attempts.count("t1") == 1
    assert store.read_events(run.id) == before
