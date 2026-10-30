"""Real, harmless process fixtures for owner cancellation and host shutdown."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.tools import background_tools as bg


def command(source: str) -> str:
    args = [sys.executable, "-c", source]
    return subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)


def wait_until(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("process fixture did not reach the expected state")


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(bg, "WORKDIR", tmp_path)
    instance = bg.BackgroundManager(bg.BackgroundScope("host-a"))
    yield instance
    if hasattr(instance, "shutdown"):
        assert instance.shutdown(timeout=8.0) == []
    else:
        for task_id in list(instance.tasks):
            instance.cancel(task_id)


def launch(manager, ready: Path) -> str:
    task_id = json.loads(
        manager.run(command(f"from pathlib import Path; import time; Path({str(ready)!r}).touch(); time.sleep(60)"))
    )["task_id"]
    wait_until(ready.exists)
    return task_id


def test_cancel_all_reaps_only_its_owner(manager, tmp_path):
    sibling = manager.for_scope(bg.BackgroundScope("host-b"))
    mine = launch(manager, tmp_path / "a")
    theirs = launch(sibling, tmp_path / "b")
    outcome = manager.cancel_all(timeout=8.0)
    assert outcome == {"requested": 1, "pending": []}
    assert json.loads(manager.check(mine))["status"] == "cancelled"
    assert json.loads(sibling.check(theirs))["status"] == "running"
    assert manager.cancel_all(timeout=0) == {"requested": 0, "pending": []}


def test_shutdown_closes_all_handles_and_reaps(manager, tmp_path):
    sibling = manager.for_scope(bg.BackgroundScope("host-b"))
    launch(manager, tmp_path / "a")
    launch(sibling, tmp_path / "b")
    assert manager.shutdown(timeout=8.0) == []
    assert json.loads(sibling.run(command("print('must not run')")))["status"] == "error"
    assert all(t["status"] == "cancelled" and t["process"] is None for t in manager.tasks.values())


def test_cancellation_during_spawn_is_reaped(manager, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = bg._start_process

    def delayed_start(cmd):
        entered.set()
        assert release.wait(5)
        return original(cmd)

    monkeypatch.setattr(bg, "_start_process", delayed_start)
    task_id = json.loads(manager.run(command("import time; time.sleep(60)")))["task_id"]
    try:
        assert entered.wait(5)
        assert manager.cancel_all(timeout=0)["pending"] == [task_id]
        assert json.loads(manager.check(task_id))["status"] == "cancelling"
    finally:
        release.set()
    assert manager.cancel_all(timeout=8)["pending"] == []
    assert json.loads(manager.check(task_id))["status"] == "cancelled"


def test_cancel_before_spawn_never_starts_command(manager, monkeypatch):
    class DeferredThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(bg.threading, "Thread", DeferredThread)
    cmd = command("print('must not run')")
    task_id = json.loads(manager.run(cmd))["task_id"]
    manager.cancel(task_id)
    monkeypatch.setattr(bg, "_start_process", lambda _: pytest.fail("cancelled before spawn"))
    manager._execute(task_id, cmd)
    assert json.loads(manager.check(task_id))["status"] == "cancelled"


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group contract; Windows has native CI")
def test_cancel_reaps_descendant_even_after_shell_exits(manager, tmp_path):
    ready = tmp_path / "child"
    child = f"import time; from pathlib import Path; Path({str(ready)!r}).touch(); time.sleep(60)"
    source = f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {child!r}])"
    task_id = json.loads(manager.run(command(source)))["task_id"]
    wait_until(ready.exists)
    wait_until(lambda: manager.tasks[task_id]["process"].poll() is not None)
    assert manager.cancel_all(timeout=8)["pending"] == []
    assert json.loads(manager.check(task_id))["status"] == "cancelled"


def test_session_cancel_reaps_background_tasks_before_its_turn_ends():
    from types import SimpleNamespace
    from src.session.service import SessionService

    calls = []
    service = SessionService.__new__(SessionService)
    manager = bg.BackgroundManager(bg.BackgroundScope("session:s1"))
    service._background_handles = {"s1": manager}
    service._active_tasks = {"s1": SimpleNamespace(done=lambda: False, cancel=lambda: calls.append("cancelled"))}
    service._active_loops = {}
    service._user_cancel_requests = set()
    service._inflight_lock = __import__("threading").Lock()
    service._inflight = set()
    service._shutting_down = False
    task_id = json.loads(manager.run(command("import time; time.sleep(60)")))["task_id"]
    assert service.cancel_current("s1") is True
    wait_until(lambda: json.loads(manager.check(task_id))["status"] == "cancelled")
    assert calls == ["cancelled"]


def test_session_shutdown_stops_new_work_and_reaps_tasks():
    import threading
    from src.session.service import SessionService

    service = SessionService.__new__(SessionService)
    service._background_handles = {"s1": bg.BackgroundManager(bg.BackgroundScope("session:s1"))}
    service._active_tasks = {}
    service._active_loops = {}
    service._inflight_lock = threading.Lock()
    service._inflight = set()
    service._shutting_down = False
    manager = service._background_handles["s1"]
    task_id = json.loads(manager.run(command("import time; time.sleep(60)")))["task_id"]
    assert service.shutdown(timeout=8.0) == []
    assert json.loads(manager.check(task_id))["status"] == "cancelled"
    # Refusal lives at the service gate: these handles share the process-wide
    # table, so closing that table would stop unrelated hosts in this process.
    service.store = SimpleNamespace(
        get_session=lambda session_id: SimpleNamespace(
            session_id=session_id,
            config={},
            last_attempt_id=None,
        )
    )
    service._search_index = SimpleNamespace(index_message=lambda *a, **k: None)
    service.event_bus = SimpleNamespace(emit=lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="shutting down"):
        __import__("asyncio").run(service.send_message("s1", "hello"))


def test_session_attempt_registers_completion_with_its_owner():
    from src.session.service import SessionService

    emitted = []
    service = SessionService.__new__(SessionService)
    service.event_bus = SimpleNamespace(
        emit=lambda session_id, event_type, data: emitted.append((session_id, event_type, data)),
    )
    service._publish_background_completion(
        "session:s1",
        {
            "task_id": "task-1",
            "status": "completed",
            "attempt_id": "a1",
            "command": "echo done",
            "exit_code": 0,
            "result": "done",
        },
    )
    # A swarm worker's owner is not a session; it must not leak onto a bus.
    service._publish_background_completion("swarm:run:agent:task", {"task_id": "t"})
    assert emitted == [
        (
            "s1",
            "background.completed",
            {
                "task_id": "task-1",
                "status": "completed",
                "attempt_id": "a1",
                "command": "echo done",
                "exit_code": 0,
                "result": "done",
            },
        )
    ]


def test_agent_stop_reaps_tasks_it_started_or_carried():
    from src.agent.loop import AgentLoop

    registry = bg.BackgroundManager(bg.BackgroundScope("session:s1"))
    task_id = json.loads(registry.run(command("import time; time.sleep(60)")))["task_id"]
    loop = AgentLoop(
        registry=SimpleNamespace(get=lambda name: None, background=registry),
        llm=SimpleNamespace(),
        max_iterations=1,
        background_manager=registry,
    )
    loop.cancel()
    wait_until(lambda: json.loads(registry.check(task_id))["status"] == "cancelled")


def test_completion_callback_keeps_originating_attempt(manager):
    seen = []
    manager._on_completion = lambda owner, payload: seen.append((owner, payload))
    handle = manager.for_scope(bg.BackgroundScope("host-a", "attempt-1"))
    task_id = json.loads(handle.run(command("print('done')")))["task_id"]
    wait_until(lambda: bool(seen))
    assert seen[0][0] == "host-a"
    assert seen[0][1]["task_id"] == task_id
    assert seen[0][1]["attempt_id"] == "attempt-1"



def test_shutdown_off_event_loop_cancels_real_async_attempt():
    import asyncio
    from src.session.service import SessionService

    async def scenario():
        stopped = asyncio.Event()
        async def work():
            try:
                await asyncio.sleep(30)
            finally:
                stopped.set()
        task = asyncio.create_task(work())
        await asyncio.sleep(0)
        service = SessionService.__new__(SessionService)
        service._inflight_lock = threading.Lock()
        service._active_loops = {}
        service._active_tasks = {"s1": task}
        service._background_handles = {}
        assert await asyncio.to_thread(service.shutdown, timeout=2) == []
        assert stopped.is_set()
        assert task.cancelled()
    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["success", "failed"])
def test_agent_terminal_status_only_cancels_background_on_failure(monkeypatch, status):
    from src.agent.loop import AgentLoop
    from unittest.mock import Mock

    loop = AgentLoop.__new__(AgentLoop)
    loop._background_manager = Mock()
    monkeypatch.setattr(loop, "_run_bound", lambda *a: {"status": status})
    assert loop.run("test")["status"] == status
    assert loop._background_manager.cancel_all.call_count == (status == "failed")
