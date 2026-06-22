"""Unit tests for src.tools.bash_tool.BashTool."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from src.tools.bash_tool import BashTool


@pytest.fixture()
def tool() -> BashTool:
    """Create a BashTool instance for testing."""
    return BashTool()


def _make_completed_process(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess:
    """Helper to build a CompletedProcess mock result."""
    return subprocess.CompletedProcess(
        args="fake",
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# ─── Normal Execution ───────────────────────────────────────────────────────────────


class TestNormalExecution:
    """Tests for normal command execution paths."""

    def test_successful_command_returns_ok(self, tool: BashTool, monkeypatch: pytest.MonkeyPatch) -> None:
        """Successful command returns status=ok and exit_code=0."""
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: _make_completed_process(stdout="hello\n")
        )
        result = json.loads(tool.execute(command="echo hello"))
        assert result["status"] == "ok"
        assert result["exit_code"] == 0

    def test_failed_command_returns_error_status(self, tool: BashTool, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-zero exit code returns status=error."""
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: _make_completed_process(returncode=1)
        )
        result = json.loads(tool.execute(command="false"))
        assert result["status"] == "error"
        assert result["exit_code"] == 1

    def test_stdout_captured(self, tool: BashTool, monkeypatch: pytest.MonkeyPatch) -> None:
        """stdout is captured correctly."""
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: _make_completed_process(stdout="output data")
        )
        result = json.loads(tool.execute(command="cmd"))
        assert result["stdout"] == "output data"

    def test_stderr_captured(self, tool: BashTool, monkeypatch: pytest.MonkeyPatch) -> None:
        """stderr is captured correctly."""
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: _make_completed_process(stderr="warn msg", returncode=0)
        )
        result = json.loads(tool.execute(command="cmd"))
        assert result["stderr"] == "warn msg"

    def test_custom_cwd_passed(self, tool: BashTool) -> None:
        """run_dir parameter is passed to subprocess as cwd."""
        captured_kwargs: dict = {}

        def _fake_run(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return _make_completed_process()

        with patch.object(subprocess, "run", side_effect=_fake_run):
            tool.execute(command="ls", run_dir="/tmp/work")

        assert captured_kwargs["cwd"] == "/tmp/work"


# ─── Output Truncation ──────────────────────────────────────────────────────────────────


class TestOutputTruncation:
    """Tests for output truncation at _OUTPUT_LIMIT."""

    def test_stdout_truncated_at_limit(self, tool: BashTool, monkeypatch: pytest.MonkeyPatch) -> None:
        """stdout exceeding 50000 chars is truncated."""
        long_output = "x" * 60_000
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: _make_completed_process(stdout=long_output)
        )
        result = json.loads(tool.execute(command="cmd"))
        assert len(result["stdout"]) == 50_000

    def test_stderr_truncated_at_limit(self, tool: BashTool, monkeypatch: pytest.MonkeyPatch) -> None:
        """stderr exceeding 50000 chars is truncated."""
        long_err = "e" * 60_000
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: _make_completed_process(stderr=long_err)
        )
        result = json.loads(tool.execute(command="cmd"))
        assert len(result["stderr"]) == 50_000

    def test_output_under_limit_not_truncated(self, tool: BashTool, monkeypatch: pytest.MonkeyPatch) -> None:
        """Output under limit is not truncated."""
        output = "a" * 49_999
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: _make_completed_process(stdout=output)
        )
        result = json.loads(tool.execute(command="cmd"))
        assert result["stdout"] == output
        assert len(result["stdout"]) == 49_999


# ─── Timeout Handling ──────────────────────────────────────────────────────────────────


class TestTimeout:
    """Tests for timeout handling."""

    def test_timeout_returns_error_json(self, tool: BashTool, monkeypatch: pytest.MonkeyPatch) -> None:
        """Timeout returns correct error JSON."""
        def _raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="sleep 999", timeout=120)

        monkeypatch.setattr(subprocess, "run", _raise_timeout)
        result = json.loads(tool.execute(command="sleep 999"))
        assert result["status"] == "error"
        assert "error" in result

    def test_timeout_message_includes_duration(self, tool: BashTool, monkeypatch: pytest.MonkeyPatch) -> None:
        """Timeout message includes 120s."""
        def _raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="sleep 999", timeout=120)

        monkeypatch.setattr(subprocess, "run", _raise_timeout)
        result = json.loads(tool.execute(command="sleep 999"))
        assert "120s" in result["error"]


# ─── Exception Handling ──────────────────────────────────────────────────────────────────


class TestExceptionHandling:
    """Tests for generic exception handling."""

    def test_generic_exception_returns_error_json(self, tool: BashTool, monkeypatch: pytest.MonkeyPatch) -> None:
        """Generic exception returns error JSON."""
        def _raise_exc(*args, **kwargs):
            raise OSError("Permission denied")

        monkeypatch.setattr(subprocess, "run", _raise_exc)
        result = json.loads(tool.execute(command="cmd"))
        assert result["status"] == "error"
        assert "error" in result

    def test_exception_message_preserved(self, tool: BashTool, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exception message is preserved."""
        msg = "Something went terribly wrong"

        def _raise_exc(*args, **kwargs):
            raise RuntimeError(msg)

        monkeypatch.setattr(subprocess, "run", _raise_exc)
        result = json.loads(tool.execute(command="cmd"))
        assert result["error"] == msg


# ─── Tool Metadata ───────────────────────────────────────────────────────────────


class TestToolMetadata:
    """Tests for tool class-level attributes."""

    def test_tool_name_is_bash(self, tool: BashTool) -> None:
        """name attribute is bash."""
        assert tool.name == "bash"

    def test_tool_is_not_readonly(self, tool: BashTool) -> None:
        """is_readonly is False."""
        assert tool.is_readonly is False

    def test_tool_is_repeatable(self, tool: BashTool) -> None:
        """repeatable is True."""
        assert tool.repeatable is True
