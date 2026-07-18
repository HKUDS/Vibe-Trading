"""Regression tests for background command lifecycle reporting."""

from __future__ import annotations

import json
import sys

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
