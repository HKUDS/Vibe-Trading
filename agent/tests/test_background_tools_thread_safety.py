"""Regression: BackgroundManager must be thread-safe.

_execute() mutated self.tasks[task_id] without holding self._lock while
check() read from self.tasks concurrently. run() also wrote to
self.tasks without the lock. A concurrent check() could observe a
partially-updated task dict (status updated but result still None).
"""

from __future__ import annotations

import json
import threading
import time

from src.tools.background_tools import BackgroundManager


def test_check_returns_running_status_immediately() -> None:
    """check() on a just-started long task must see 'running'."""
    mgr = BackgroundManager()
    result = mgr.run("sleep 2")
    task_id = json.loads(result)["task_id"]
    status = json.loads(mgr.check(task_id))["status"]
    assert status == "running"


def test_check_returns_completed_after_task_finishes() -> None:
    """check() after a fast task finishes must see 'completed' and the output."""
    mgr = BackgroundManager()
    result = mgr.run("echo hello")
    task_id = json.loads(result)["task_id"]
    time.sleep(0.5)
    info = json.loads(mgr.check(task_id))
    assert info["status"] == "completed"
    assert "hello" in info["result"]


def test_check_unknown_task() -> None:
    mgr = BackgroundManager()
    info = json.loads(mgr.check("nonexistent"))
    assert info["status"] == "error"
    assert "Unknown task" in info["error"]


def test_check_all_returns_summary() -> None:
    mgr = BackgroundManager()
    mgr.run("echo a")
    mgr.run("echo b")
    time.sleep(0.5)
    summary = mgr.check()
    assert "echo a" in summary
    assert "echo b" in summary


def test_drain_notifications() -> None:
    mgr = BackgroundManager()
    mgr.run("echo test")
    time.sleep(0.5)
    notifs = mgr.drain_notifications()
    assert len(notifs) == 1
    assert notifs[0]["status"] == "completed"
    # Second drain is empty.
    assert mgr.drain_notifications() == []


def test_concurrent_check_never_sees_partial_update() -> None:
    """A concurrent check() must never see status='completed' with result=None.

    Before the fix, _execute set status before result without holding the
    lock. A racing check() could observe the intermediate state where
    status is updated but result is still None (reported as '(running)').
    """
    mgr = BackgroundManager()
    result = mgr.run("echo hello")
    task_id = json.loads(result)["task_id"]

    observed_partial = threading.Event()
    iterations = 1000

    def _poll() -> None:
        for _ in range(iterations):
            info = json.loads(mgr.check(task_id))
            # 'completed' with result='(running)' means we caught the
            # intermediate state: status was set but result was not.
            if info["status"] == "completed" and info["result"] == "(running)":
                observed_partial.set()
                return

    poller = threading.Thread(target=_poll)
    poller.start()
    poller.join(timeout=5)
    assert not observed_partial.is_set(), (
        "check() observed status='completed' with result='(running)' — "
        "a partial update leaked through the missing lock"
    )


def test_concurrent_run_and_check_no_crash() -> None:
    """Multiple threads running and checking simultaneously must not crash."""
    mgr = BackgroundManager()
    errors: list[Exception] = []

    def _worker() -> None:
        try:
            for _ in range(50):
                r = mgr.run("echo x")
                tid = json.loads(r)["task_id"]
                mgr.check(tid)
                mgr.check()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert errors == []
