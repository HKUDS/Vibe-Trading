"""Regression tests for background command lifecycle reporting."""

from __future__ import annotations

import json
import os
import shlex
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.tools import background_tools
from src.tools.background_tools import BackgroundManager


def _execute(manager: BackgroundManager, task_id: str, command: str) -> dict:
    manager.tasks[task_id] = {
        "status": "running",
        "result": None,
        "command": command,
        "exit_code": None,
    }
    manager._execute(task_id, command)
    return manager.tasks[task_id]


def test_nonzero_exit_is_reported_as_error() -> None:
    manager = BackgroundManager()
    command = f'"{sys.executable}" -c "import sys; print(\'failed output\'); sys.exit(7)"'

    task = _execute(manager, "failed", command)

    assert task["status"] == "error"
    assert task["exit_code"] == 7
    assert "failed output" in task["result"]
    checked = json.loads(manager.check("failed"))
    assert checked["status"] == "error"
    assert checked["exit_code"] == 7
    assert manager.drain_notifications() == [
        {
            "task_id": "failed",
            "status": "error",
            "command": command[:80],
            "result": "failed output",
            "exit_code": 7,
        }
    ]


def test_cancel_unknown_task_returns_actionable_error() -> None:
    manager = BackgroundManager()

    result = json.loads(manager.cancel("missing"))

    assert result == {
        "status": "error",
        "error": "Unknown task missing",
    }


def test_check_running_task_reports_timeout_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = BackgroundManager()
    manager.tasks["slow"] = {
        "status": "running",
        "result": None,
        "command": "python slow.py",
        "exit_code": None,
        "process": None,
        "cancel_requested": False,
        "started_at": 100.0,
    }
    monkeypatch.setattr(background_tools.time, "monotonic", lambda: 297.0)

    result = json.loads(manager.check("slow"))

    assert result["status"] == "running"
    assert result["elapsed_seconds"] == 197.0
    assert result["timeout_seconds"] == 300.0
    assert result["timeout_remaining_seconds"] == 103.0
    assert "cancel_background" in result["result"]


def test_cancel_targets_only_the_tracked_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = BackgroundManager()
    target = MagicMock()
    target.poll.return_value = None
    target.pid = 4321
    sibling = MagicMock()
    sibling.poll.return_value = None
    sibling.pid = 8765
    manager.tasks = {
        "target": {
            "status": "running",
            "result": None,
            "command": "python target.py",
            "exit_code": None,
            "process": target,
            "cancel_requested": False,
        },
        "sibling": {
            "status": "running",
            "result": None,
            "command": "python sibling.py",
            "exit_code": None,
            "process": sibling,
            "cancel_requested": False,
        },
    }
    stopped: list[object] = []
    monkeypatch.setattr(
        background_tools,
        "_force_stop_process_tree",
        stopped.append,
    )

    result = json.loads(manager.cancel("target"))

    assert result == {
        "status": "ok",
        "task_id": "target",
        "task_status": "cancelling",
        "message": "Cancellation requested",
    }
    assert stopped == [target]
    assert manager.tasks["target"]["status"] == "cancelling"
    assert manager.tasks["target"]["cancel_requested"] is True
    assert manager.tasks["sibling"]["status"] == "running"
    assert manager.tasks["sibling"]["cancel_requested"] is False


def test_cancel_completed_task_does_not_touch_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = BackgroundManager()
    process = MagicMock()
    manager.tasks["done"] = {
        "status": "completed",
        "result": "finished",
        "command": "python done.py",
        "exit_code": 0,
        "process": process,
        "cancel_requested": False,
    }
    stop = MagicMock()
    monkeypatch.setattr(background_tools, "_force_stop_process_tree", stop)

    result = json.loads(manager.cancel("done"))

    assert result == {
        "status": "error",
        "error": "Task done is already completed",
        "task_status": "completed",
    }
    stop.assert_not_called()


def test_cancel_background_tool_contract() -> None:
    tool = background_tools.CancelBackgroundTool()

    assert tool.name == "cancel_background"
    assert tool.parameters["required"] == ["task_id"]
    assert tool.is_readonly is False


def test_windows_process_tree_kill_uses_pid_never_image_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = MagicMock()
    process.pid = 4321
    run = MagicMock()
    monkeypatch.setattr(background_tools.subprocess, "run", run)

    background_tools._taskkill_windows_process_tree(process)

    args = run.call_args.args[0]
    assert args == ["taskkill", "/PID", "4321", "/T", "/F"]
    assert "/IM" not in args
    assert "python.exe" not in args


@pytest.mark.parametrize(
    "command",
    [
        'taskkill /F /IM python.exe 2>nul & echo "done"',
        (
            "taskkill /F /PID (Get-Process python | "
            "Where-Object {$_.MainWindowTitle -eq ''} | "
            "Select-Object -First 1 -ExpandProperty Id)"
        ),
    ],
)
def test_background_run_rejects_broad_python_termination(command: str) -> None:
    manager = BackgroundManager()

    result = json.loads(manager.run(command))

    assert result["status"] == "error"
    assert "cancel_background" in result["error"]
    assert manager.tasks == {}


def _wait_for_task_status(
    manager: BackgroundManager,
    task_id: str,
    expected: set[str],
    timeout: float = 5.0,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = json.loads(manager.check(task_id))
        if task["status"] in expected:
            return task
        time.sleep(0.02)
    pytest.fail(
        f"task {task_id} did not reach {sorted(expected)}: "
        f"{manager.check(task_id)}"
    )


def _wait_for_registered_process(
    manager: BackgroundManager,
    task_id: str,
    timeout: float = 5.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with manager._lock:
            process = manager.tasks[task_id].get("process")
        if process is not None:
            return
        time.sleep(0.02)
    pytest.fail(f"task {task_id} did not register its process")


def test_cancel_running_task_reaps_process() -> None:
    manager = BackgroundManager()
    command = f'"{sys.executable}" -c "import time; time.sleep(30)"'
    task_id = json.loads(manager.run(command))["task_id"]
    _wait_for_registered_process(manager, task_id)

    result = json.loads(manager.cancel(task_id))
    task = _wait_for_task_status(manager, task_id, {"cancelled"})

    assert result["status"] == "ok"
    assert task["status"] == "cancelled"
    assert task["exit_code"] not in (None, 0)
    assert "Cancelled by request" in task["result"]


def test_cancel_running_task_leaves_sibling_alive() -> None:
    manager = BackgroundManager()
    command = f'"{sys.executable}" -c "import time; time.sleep(30)"'
    target_id = json.loads(manager.run(command))["task_id"]
    sibling_id = json.loads(manager.run(command))["task_id"]
    _wait_for_registered_process(manager, target_id)
    _wait_for_registered_process(manager, sibling_id)

    try:
        result = json.loads(manager.cancel(target_id))
        target = _wait_for_task_status(manager, target_id, {"cancelled"})
        sibling = json.loads(manager.check(sibling_id))

        assert result["status"] == "ok"
        assert target["status"] == "cancelled"
        assert sibling["status"] == "running"
    finally:
        sibling = json.loads(manager.check(sibling_id))
        if sibling["status"] in {"running", "cancelling"}:
            manager.cancel(sibling_id)
            _wait_for_task_status(manager, sibling_id, {"cancelled"})


def test_cancel_before_process_registration_is_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = BackgroundManager()
    start_entered = threading.Event()
    allow_start = threading.Event()
    process = MagicMock()
    process.pid = 4321
    process.poll.return_value = None
    process.communicate.return_value = ("", "")
    process.returncode = -9
    stop = MagicMock()

    def delayed_start(command: str) -> object:
        del command
        start_entered.set()
        assert allow_start.wait(timeout=2.0)
        return process

    monkeypatch.setattr(background_tools, "_start_process", delayed_start)
    monkeypatch.setattr(background_tools, "_force_stop_process_tree", stop)

    task_id = json.loads(manager.run("python slow.py"))["task_id"]
    assert start_entered.wait(timeout=2.0)
    result = json.loads(manager.cancel(task_id))
    allow_start.set()
    task = _wait_for_task_status(manager, task_id, {"cancelled"})

    assert result["status"] == "ok"
    assert task["status"] == "cancelled"
    stop.assert_called_once_with(process)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
def test_timeout_kills_descendant_and_reaps_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_marker = tmp_path / "child-started"
    orphan_marker = tmp_path / "orphan-wrote-after-timeout"
    child_code = (
        "import time; from pathlib import Path; "
        f"Path({str(started_marker)!r}).write_text('started', encoding='utf-8'); "
        "time.sleep(1.5); "
        f"Path({str(orphan_marker)!r}).write_text('orphan', encoding='utf-8')"
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(child_code)} & wait"
    processes: list[background_tools.subprocess.Popen[str]] = []
    real_popen = background_tools.subprocess.Popen

    def tracked_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(background_tools, "_COMMAND_TIMEOUT_SECONDS", 0.8)
    monkeypatch.setattr(background_tools, "_TERMINATION_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(background_tools.subprocess, "Popen", tracked_popen)

    manager = BackgroundManager()
    task = _execute(manager, "timeout", command)

    assert started_marker.exists()
    assert task["status"] == "timeout"
    assert processes[0].poll() is not None
    time.sleep(1.0)
    assert not orphan_marker.exists()
