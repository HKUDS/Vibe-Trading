"""Regression tests for continuing a persisted CLI conversation.

The history a continuation sends is replayed from the session's thread log by
``_run_agent``; ``tests/test_cli_conversation.py`` covers it end to end. These
tests pin which directory and session a continuation lands in.
"""

from __future__ import annotations

import cli.commands.common as _cmd_common
import cli.commands.execution as _cmd_execution

from pathlib import Path

from src.session.thread import ThreadLog


def test_repeated_continue_reads_and_appends_one_canonical_trace(
    tmp_path, monkeypatch
) -> None:
    """Every continuation of a session lands in that session's trace directory."""
    runs_dir = tmp_path / "runs"
    sessions_dir = tmp_path / "sessions"
    trace_dir = sessions_dir / "session-1"

    writer = ThreadLog(trace_dir / "thread.jsonl")
    writer.append("turn_start", "initial", prompt="initial question")
    writer.append("assistant", "initial", content="initial answer", phase="final")

    seen = []

    def fake_run_agent(prompt, run_dir_override, **kwargs):
        # The caller no longer builds a history: ``_run_agent`` replays it.
        assert "history" not in kwargs
        seen.append((prompt, run_dir_override, kwargs["session_id"]))
        continuation = ThreadLog(Path(run_dir_override) / "thread.jsonl")
        continuation.append("turn_start", prompt, prompt=prompt)
        continuation.append("assistant", prompt, content=f"answer to {prompt}", phase="final")
        return {"status": "success", "run_id": "session-1", "run_dir": run_dir_override}

    monkeypatch.setattr(_cmd_common, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(_cmd_common, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(_cmd_execution, "_run_agent", fake_run_agent)
    monkeypatch.setattr(_cmd_execution, "_print_json_result", lambda result: None)

    assert (
        _cmd_execution.cmd_continue("session-1", "first follow-up", 5, json_mode=True)
        == _cmd_common.EXIT_SUCCESS
    )
    assert (
        _cmd_execution.cmd_continue("session-1", "second follow-up", 5, json_mode=True)
        == _cmd_common.EXIT_SUCCESS
    )

    assert seen == [
        ("first follow-up", str(trace_dir), "session-1"),
        ("second follow-up", str(trace_dir), "session-1"),
    ]
    assert not (runs_dir / "session-1").exists()
