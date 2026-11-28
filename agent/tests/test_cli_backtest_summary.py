"""CLI backtest summary: metric parsing, English labels, and no spawned server."""

from __future__ import annotations

import cli.commands.common as _cmd_common
import cli.commands.execution as _cmd_execution

import subprocess
from pathlib import Path

from rich.console import Console
from unittest.mock import Mock

from cli.commands.inspection import _read_metric_values

_METRICS_CSV = (
    "total_return,annual_return,sharpe,max_drawdown,win_rate,trade_count\n"
    "0.824,0.131,1.08,-0.187,0.564,42\n"
)


def _run_with_metrics(tmp_path: Path) -> Path:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "metrics.csv").write_text(_METRICS_CSV, encoding="utf-8")
    return tmp_path


def _forbid_spawn(monkeypatch) -> None:
    """Fail the test if anything starts a process from a print path.

    The original implementation launched `cli.commands.dispatch serve` detached, with
    stdout discarded and no shutdown, so every run that produced a backtest could
    leave an unauthenticated loopback API listening after the CLI exited.
    """

    def _explode(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError(f"printing a result must not spawn a process: {args!r}")

    monkeypatch.setattr(subprocess, "Popen", _explode)


def test_read_metric_values_parses_floats(tmp_path: Path) -> None:
    run_dir = _run_with_metrics(tmp_path)

    metrics = _read_metric_values(run_dir / "artifacts" / "metrics.csv")

    assert metrics["total_return"] == 0.824
    assert metrics["trade_count"] == 42.0


def test_read_metric_values_returns_empty_when_absent(tmp_path: Path) -> None:
    assert _read_metric_values(tmp_path / "artifacts" / "metrics.csv") == {}


def test_interactive_result_prints_english_metrics_and_a_hint(
    tmp_path: Path, monkeypatch
) -> None:
    from cli.main import _print_interactive_result

    _forbid_spawn(monkeypatch)
    run_dir = _run_with_metrics(tmp_path)
    console = Console(record=True, force_terminal=False, color_system=None, width=100)

    _print_interactive_result(
        console,
        {
            "status": "success",
            "run_id": "run_123",
            "run_dir": str(run_dir),
            "content": "Done.",
        },
        3.5,
    )
    output = console.export_text()

    assert "Backtest complete" in output
    assert "82.4%" in output
    assert "Sharpe" in output and "1.08" in output
    assert "run_123" in output
    # The dashboard is named, not started.
    assert "vibe-trading serve" in output
    assert "/runs/run_123?view=dashboard" in output
    # CLI output is English, per the project's UI default.
    assert "回测" not in output and "报告" not in output


def test_single_prompt_run_prints_the_hint_without_serving(
    tmp_path: Path, monkeypatch
) -> None:
    pass
    from src import preflight

    _forbid_spawn(monkeypatch)
    run_dir = _run_with_metrics(tmp_path)
    result = {
        "status": "success",
        "run_id": "single-run",
        "run_dir": str(run_dir),
        "content": "Done.",
    }
    monkeypatch.setattr(preflight, "run_preflight", lambda console: [])
    monkeypatch.setattr(_cmd_execution, "_ensure_session_id", lambda prompt: "session")
    monkeypatch.setattr(_cmd_execution, "_run_agent", lambda *args, **kwargs: result)
    monkeypatch.setattr(_cmd_execution, "_print_result", Mock())
    test_console = Console(record=True, force_terminal=False, color_system=None, width=100)
    monkeypatch.setattr(_cmd_common, "console", test_console)

    exit_code = _cmd_execution.cmd_run("Backtest AAPL", 10)
    output = test_console.export_text()

    assert exit_code == 0
    assert "vibe-trading serve" in output
    assert "/runs/single-run?view=dashboard" in output


def test_no_hint_when_the_turn_produced_no_backtest(tmp_path: Path, monkeypatch) -> None:
    from cli.main import _print_interactive_result

    _forbid_spawn(monkeypatch)
    console = Console(record=True, force_terminal=False, color_system=None, width=100)

    _print_interactive_result(
        console,
        {"status": "success", "run_id": "run_9", "run_dir": str(tmp_path), "content": "Hi."},
        1.0,
    )
    output = console.export_text()

    assert "Backtest complete" not in output
    assert "view=dashboard" not in output
