"""Safety regression tests for host shell execution."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.tools import bash_tool
from src.tools.bash_tool import BashTool


@pytest.mark.parametrize(
    "command",
    [
        'taskkill /F /IM python.exe 2>nul & echo "killed any python"',
        (
            "taskkill /F /PID (Get-Process python | "
            "Where-Object {$_.MainWindowTitle -eq ''} | "
            "Select-Object -First 1 -ExpandProperty Id)"
        ),
        'powershell -Command "taskkill /F /IM python.exe"',
        'start "" taskkill /F /IM python.exe',
        "powershell -NoProfile -Command \"Stop-Process -Name python -Force\"",
        "powershell -Command \"Get-Process python | Stop-Process -Force\"",
        "pkill -9 -f python",
        "killall python3",
    ],
)
def test_rejects_broad_python_process_termination(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = MagicMock(side_effect=AssertionError("unsafe command reached subprocess"))
    monkeypatch.setattr(bash_tool.subprocess, "run", run)

    result = json.loads(BashTool().execute(command=command))

    assert result["status"] == "error"
    assert "cancel_background" in result["error"]
    run.assert_not_called()


@pytest.mark.parametrize(
    "command",
    [
        "python --version",
        "taskkill /PID 4321 /T /F",
        "echo python.exe",
    ],
)
def test_allows_non_broad_process_commands(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = MagicMock()
    run.return_value.returncode = 0
    run.return_value.stdout = "ok"
    run.return_value.stderr = ""
    monkeypatch.setattr(bash_tool.subprocess, "run", run)

    result = json.loads(BashTool().execute(command=command))

    assert result["status"] == "ok"
    run.assert_called_once()
