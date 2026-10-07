"""The backtest tool must record state.json so evidence ingestion can tell run status.

refresh_strategy_evidence fail-closes on runs without state.json, which used to
be written only by the runtime loop — so every tool-driven run was rejected as
unknown-provenance despite complete artifacts (#1412). These tests pin the
tool-side lifecycle recording: success and failure after an engine execution,
and no state file when validation rejects the run before the engine starts.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest

from src.tools.backtest_tool import run_backtest


@dataclass
class _FakeRunResult:
    success: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    artifacts: dict = field(default_factory=dict)


@pytest.fixture()
def tool_run_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    run_dir = tmp_path / "run"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "config.json").write_text(json.dumps({"source": "yfinance"}), encoding="utf-8")
    (run_dir / "code" / "signal_engine.py").write_text("", encoding="utf-8")
    return run_dir


def _run_with_result(run_dir: Path, result: _FakeRunResult) -> dict:
    with patch("src.tools.backtest_tool.emit_progress"), patch("src.tools.backtest_tool.Runner") as runner_cls:
        runner_cls.return_value.execute.return_value = result
        return json.loads(run_backtest(str(run_dir)))


def test_successful_run_records_state_success(tool_run_dir):
    envelope = _run_with_result(tool_run_dir, _FakeRunResult(success=True, exit_code=0))

    assert envelope["status"] == "ok"
    state = json.loads((tool_run_dir / "state.json").read_text(encoding="utf-8"))
    assert state == {"status": "success"}


def test_failed_run_records_state_failed_with_exit_code(tool_run_dir):
    envelope = _run_with_result(tool_run_dir, _FakeRunResult(success=False, exit_code=3, stderr="boom"))

    assert envelope["status"] == "error"
    state = json.loads((tool_run_dir / "state.json").read_text(encoding="utf-8"))
    assert state == {"status": "failed", "reason": "backtest engine exited with code 3"}


def test_validation_error_records_no_state(tool_run_dir):
    (tool_run_dir / "config.json").unlink()

    envelope = json.loads(run_backtest(str(tool_run_dir)))

    assert envelope["status"] == "error"
    assert not (tool_run_dir / "state.json").exists()


def test_validation_error_names_the_directory_it_checked(tool_run_dir):
    """The path matters: a caller whose run_dir was supplied by someone else
    (e.g. a swarm worker injecting the agent workspace) has no way to tell that
    the tool looked somewhere other than the path it passed."""
    (tool_run_dir / "config.json").unlink()

    envelope = json.loads(run_backtest(str(tool_run_dir)))

    assert str(tool_run_dir) in envelope["error"]
    assert "hint" in envelope, "mirrors autopilot_tool's missing-artifact envelope"


def test_missing_signal_engine_names_the_directory_it_checked(tool_run_dir):
    (tool_run_dir / "code" / "signal_engine.py").unlink()

    envelope = json.loads(run_backtest(str(tool_run_dir)))

    assert envelope["status"] == "error"
    assert str(tool_run_dir) in envelope["error"]
    assert "hint" in envelope


def test_timeout_records_state_failed_and_returns_error_envelope(tool_run_dir):
    with patch("src.tools.backtest_tool.emit_progress"), patch("src.tools.backtest_tool.Runner") as runner_cls:
        runner_cls.return_value.timeout = 300
        runner_cls.return_value.execute.side_effect = subprocess.TimeoutExpired(cmd="runner.py", timeout=300)
        envelope = json.loads(run_backtest(str(tool_run_dir)))

    assert envelope["status"] == "error"
    assert envelope["error"] == "backtest engine timed out after 300s"
    state = json.loads((tool_run_dir / "state.json").read_text(encoding="utf-8"))
    assert state == {"status": "failed", "reason": "backtest engine timed out after 300s"}


def test_backtest_uses_configured_tool_timeout(tool_run_dir, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_TOOL_TIMEOUT_SECONDS", "42")
    with patch("src.tools.backtest_tool.emit_progress"), patch("src.tools.backtest_tool.Runner") as runner_cls:
        runner_cls.return_value.execute.return_value = _FakeRunResult(success=True, exit_code=0)
        run_backtest(str(tool_run_dir))

    assert runner_cls.call_args.kwargs == {"timeout": 42.0}


def test_timeout_persists_partial_runner_output(tool_run_dir):
    timeout = subprocess.TimeoutExpired(
        cmd="runner.py", timeout=300, output="partial stdout", stderr="partial stderr"
    )
    with patch("src.tools.backtest_tool.emit_progress"), patch("src.tools.backtest_tool.Runner") as runner_cls:
        runner_cls.return_value.timeout = 300
        runner_cls.return_value.execute.side_effect = timeout
        envelope = json.loads(run_backtest(str(tool_run_dir)))

    assert envelope["stdout"] == "partial stdout"
    assert envelope["stderr"] == "partial stderr"
    assert (tool_run_dir / "logs" / "runner_stdout.txt").read_text() == "partial stdout"
    assert (tool_run_dir / "logs" / "runner_stderr.txt").read_text() == "partial stderr"
