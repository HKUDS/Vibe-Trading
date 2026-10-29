"""Safety regression tests for host shell execution."""

from __future__ import annotations

from tests.module_os_helpers import patch_module_os

import json
import subprocess
from unittest.mock import MagicMock

import pytest

from src.tools import bash_tool
from src.tools.bash_tool import BashTool


class _FakePopen:
    """Minimal Popen stand-in for the allowed-command path."""

    def __init__(self, returncode: int = 0, stdout: str = "ok", stderr: str = "") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    def communicate(self, timeout: float | None = None):
        del timeout
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    def poll(self):
        return self.returncode


class _HangingPopen:
    """Popen stand-in that always times out on communicate."""

    def __init__(self) -> None:
        self.returncode = None
        self.killed = False

    def communicate(self, timeout: float | None = None):
        raise subprocess.TimeoutExpired(cmd="hang", timeout=timeout)

    def kill(self) -> None:
        self.killed = True

    def poll(self):
        return None


def _install_fake_popen(monkeypatch: pytest.MonkeyPatch, popen: _FakePopen) -> None:
    monkeypatch.setattr(bash_tool.subprocess, "Popen", lambda *a, **k: popen)


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
    popen = MagicMock(side_effect=AssertionError("unsafe command reached subprocess"))
    monkeypatch.setattr(bash_tool.subprocess, "Popen", popen)

    result = json.loads(BashTool().execute(command=command))

    assert result["status"] == "error"
    assert "cancel_background" in result["error"]
    popen.assert_not_called()


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
    fake = _FakePopen()
    _install_fake_popen(monkeypatch, fake)

    result = json.loads(BashTool().execute(command=command))

    assert result["status"] == "ok"
    assert result["exit_code"] == 0


def test_timeout_kills_process_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """A timed-out command must kill the tree and report tool_timeout.

    Regression for the 2026-08-20 hang: on Windows, killing only cmd.exe
    leaves grandchildren (e.g. piped findstr) holding the stdout/stderr
    pipe handles, so a bare subprocess.run timeout never returns. The tool
    must spawn a dedicated process group and kill the WHOLE tree, then
    return a bounded tool_timeout error.
    """
    hanging = _HangingPopen()
    _install_fake_popen(monkeypatch, hanging)
    kills: list[int] = []

    def _fake_kill(proc) -> None:
        kills.append(proc.pid if hasattr(proc, "pid") else 0)

    monkeypatch.setattr(bash_tool, "_kill_process_tree", _fake_kill)

    result = json.loads(BashTool().execute(command="echo hang"))

    assert result["status"] == "error"
    assert result["error_code"] == "tool_timeout"
    assert "timed out" in result["error"]
    assert len(kills) == 1


def test_heredoc_unsupported_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_module_os(monkeypatch, bash_tool, name="nt")
    popen = MagicMock(side_effect=AssertionError("heredoc reached subprocess"))
    monkeypatch.setattr(bash_tool.subprocess, "Popen", popen)

    result = json.loads(BashTool().execute(command="cat <<EOF\nhello\nEOF"))

    assert result["status"] == "error"
    assert result["error_code"] == "heredoc_unsupported"
    popen.assert_not_called()


def test_heredoc_allowed_on_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    """POSIX shells support heredocs natively; the command must reach the
    real shell instead of being rejected with a Windows-only error.
    """
    patch_module_os(monkeypatch, bash_tool, name="posix")
    fake = _FakePopen()
    _install_fake_popen(monkeypatch, fake)

    result = json.loads(BashTool().execute(command="cat <<EOF\nhello\nEOF"))

    assert result["status"] == "ok"
