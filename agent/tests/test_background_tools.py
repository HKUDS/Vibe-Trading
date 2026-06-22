"""Unit tests for src.tools.background_tools — BackgroundManager & Tool classes."""

from __future__ import annotations

import json
import subprocess
import threading

import pytest

from src.tools.background_tools import (
    BackgroundManager,
    BackgroundRunTool,
    CheckBackgroundTool,
)


@pytest.fixture()
def mgr() -> BackgroundManager:
    """Create a fresh BackgroundManager instance per test."""
    return BackgroundManager()


def _make_completed_process(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess:
    """Helper to build a CompletedProcess mock result."""
    return subprocess.CompletedProcess(args="fake", returncode=returncode, stdout=stdout, stderr=stderr)


# ─── Basic Functionality ─────────────────────────────────────────────────────────


class TestRunBasic:
    """Tests for BackgroundManager.run() basic behaviour."""

    def test_run_returns_valid_json_with_task_id(self, mgr: BackgroundManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """run() returns valid JSON with task_id."""
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _make_completed_process())
        result = json.loads(mgr.run("echo hi"))
        assert "task_id" in result
        assert result["status"] == "ok"
        assert len(result["task_id"]) == 8

    def test_run_task_initial_status_is_running(self, mgr: BackgroundManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """New task initial status is running."""
        barrier = threading.Barrier(2, timeout=3)

        def _blocking_run(*args, **kwargs):
            barrier.wait()
            return _make_completed_process()

        monkeypatch.setattr(subprocess, "run", _blocking_run)
        result = json.loads(mgr.run("sleep 1"))
        task_id = result["task_id"]
        # Check status before background thread executes
        assert mgr.tasks[task_id]["status"] == "running"
        barrier.wait()  # Release background thread

    def test_execute_success_sets_completed(self, mgr: BackgroundManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """Successful execution sets status to completed."""
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _make_completed_process(stdout="done"))
        mgr.tasks["t1"] = {"status": "running", "result": None, "command": "echo done"}
        mgr._execute("t1", "echo done")
        assert mgr.tasks["t1"]["status"] == "completed"
        assert mgr.tasks["t1"]["result"] == "done"

    def test_execute_combines_stdout_stderr(self, mgr: BackgroundManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """Output combines stdout and stderr."""
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: _make_completed_process(stdout="OUT\n", stderr="ERR\n")
        )
        mgr.tasks["t1"] = {"status": "running", "result": None, "command": "cmd"}
        mgr._execute("t1", "cmd")
        assert "OUT" in mgr.tasks["t1"]["result"]
        assert "ERR" in mgr.tasks["t1"]["result"]


# ─── Timeout and Exception Handling ───────────────────────────────────────────────


class TestExceptionHandling:
    """Tests for timeout and generic exception paths."""

    def test_timeout_sets_status_timeout(self, mgr: BackgroundManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """Subprocess timeout sets status to timeout."""
        def _raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="sleep 999", timeout=300)

        monkeypatch.setattr(subprocess, "run", _raise_timeout)
        mgr.tasks["t1"] = {"status": "running", "result": None, "command": "sleep 999"}
        mgr._execute("t1", "sleep 999")
        assert mgr.tasks["t1"]["status"] == "timeout"
        assert "Timeout" in mgr.tasks["t1"]["result"]

    def test_generic_exception_sets_status_error(self, mgr: BackgroundManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """Generic exception sets status to error."""
        def _raise_exc(*args, **kwargs):
            raise OSError("Permission denied")

        monkeypatch.setattr(subprocess, "run", _raise_exc)
        mgr.tasks["t1"] = {"status": "running", "result": None, "command": "cmd"}
        mgr._execute("t1", "cmd")
        assert mgr.tasks["t1"]["status"] == "error"
        assert "Permission denied" in mgr.tasks["t1"]["result"]

    def test_empty_output_replaced_with_no_output(self, mgr: BackgroundManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty output is replaced with '(no output)'."""
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _make_completed_process(stdout="", stderr=""))
        mgr.tasks["t1"] = {"status": "running", "result": None, "command": "cmd"}
        mgr._execute("t1", "cmd")
        assert mgr.tasks["t1"]["result"] == "(no output)"


# ─── Output Truncation ────────────────────────────────────────────────────────────


class TestOutputTruncation:
    """Tests for output truncation at 50000 chars."""

    def test_output_truncated_at_50000_chars(self, mgr: BackgroundManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """Long output is truncated at 50000 chars."""
        long_output = "x" * 60_000
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _make_completed_process(stdout=long_output))
        mgr.tasks["t1"] = {"status": "running", "result": None, "command": "cmd"}
        mgr._execute("t1", "cmd")
        assert len(mgr.tasks["t1"]["result"]) == 50_000


# ─── check() Behaviour ────────────────────────────────────────────────────────────


class TestCheck:
    """Tests for BackgroundManager.check() method."""

    def test_check_unknown_task_returns_error(self, mgr: BackgroundManager) -> None:
        """Querying unknown task returns error."""
        result = json.loads(mgr.check("nonexistent"))
        assert result["status"] == "error"
        assert "Unknown task" in result["error"]

    def test_check_specific_task_returns_status(self, mgr: BackgroundManager) -> None:
        """Querying specific task returns full status."""
        mgr.tasks["abc123"] = {"status": "completed", "result": "output", "command": "echo hello"}
        result = json.loads(mgr.check("abc123"))
        assert result["status"] == "completed"
        assert result["command"] == "echo hello"
        assert result["result"] == "output"

    def test_check_all_lists_all_tasks(self, mgr: BackgroundManager) -> None:
        """check() with no args lists all tasks."""
        mgr.tasks["aaa"] = {"status": "running", "result": None, "command": "cmd1"}
        mgr.tasks["bbb"] = {"status": "completed", "result": "ok", "command": "cmd2"}
        output = mgr.check()
        assert "aaa" in output
        assert "bbb" in output
        assert "[running]" in output
        assert "[completed]" in output

    def test_check_no_tasks_returns_message(self, mgr: BackgroundManager) -> None:
        """Returns 'No background tasks.' when empty."""
        assert mgr.check() == "No background tasks."


# ─── Notification Queue ───────────────────────────────────────────────────────────


class TestNotifications:
    """Tests for notification queue behaviour."""

    def test_notification_appended_on_completion(self, mgr: BackgroundManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """Notification is appended on task completion."""
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _make_completed_process(stdout="ok"))
        mgr.tasks["t1"] = {"status": "running", "result": None, "command": "echo ok"}
        mgr._execute("t1", "echo ok")
        assert len(mgr._notifications) == 1
        assert mgr._notifications[0]["task_id"] == "t1"
        assert mgr._notifications[0]["status"] == "completed"

    def test_drain_notifications_returns_and_clears(self, mgr: BackgroundManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """drain returns notifications and clears queue."""
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _make_completed_process(stdout="x"))
        mgr.tasks["t1"] = {"status": "running", "result": None, "command": "cmd"}
        mgr._execute("t1", "cmd")
        notifs = mgr.drain_notifications()
        assert len(notifs) == 1
        assert notifs[0]["task_id"] == "t1"
        # Queue is now empty
        assert mgr.drain_notifications() == []

    def test_drain_empty_returns_empty_list(self, mgr: BackgroundManager) -> None:
        """drain returns empty list when no notifications."""
        assert mgr.drain_notifications() == []


# ─── Concurrency Safety ───────────────────────────────────────────────────────────


class TestConcurrency:
    """Tests for thread safety — W-1 defect verification."""

    def test_concurrent_run_and_check_no_crash(self, mgr: BackgroundManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """Concurrent run + check does not crash."""
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _make_completed_process(stdout="ok"))
        errors: list = []
        barrier = threading.Barrier(10, timeout=3)

        def _worker():
            try:
                barrier.wait()
                result = json.loads(mgr.run("echo hi"))
                mgr.check(result["task_id"])
                mgr.check()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)
        assert errors == []

    def test_concurrent_multiple_tasks_no_lost_notifications(
        self, mgr: BackgroundManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Concurrent tasks do not lose notifications."""
        call_count = 20
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _make_completed_process(stdout="done"))
        barrier = threading.Barrier(call_count, timeout=3)

        def _worker(tid: str):
            mgr.tasks[tid] = {"status": "running", "result": None, "command": f"cmd-{tid}"}
            barrier.wait()
            mgr._execute(tid, f"cmd-{tid}")

        threads = [threading.Thread(target=_worker, args=(f"task{i}",)) for i in range(call_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)

        notifs = mgr.drain_notifications()
        assert len(notifs) == call_count


# ─── Tool Class Tests ─────────────────────────────────────────────────────────────


class TestToolClasses:
    """Tests for BackgroundRunTool and CheckBackgroundTool delegation."""

    def test_background_run_tool_delegates_to_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BackgroundRunTool.execute delegates to manager."""
        import src.tools.background_tools as bg_mod

        fake_mgr = BackgroundManager()
        monkeypatch.setattr(bg_mod, "_BG", fake_mgr)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _make_completed_process(stdout="bg"))

        tool = BackgroundRunTool()
        result = json.loads(tool.execute(command="echo bg"))
        assert result["status"] == "ok"
        assert result["task_id"] in fake_mgr.tasks

    def test_check_background_tool_delegates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CheckBackgroundTool.execute delegates to manager."""
        import src.tools.background_tools as bg_mod

        fake_mgr = BackgroundManager()
        fake_mgr.tasks["xyz"] = {"status": "completed", "result": "ok", "command": "ls"}
        monkeypatch.setattr(bg_mod, "_BG", fake_mgr)

        tool = CheckBackgroundTool()
        result = json.loads(tool.execute(task_id="xyz"))
        assert result["status"] == "completed"
