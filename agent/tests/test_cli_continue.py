"""Regression tests for continuing a persisted CLI conversation.

The history a continuation sends is replayed from the session's thread log by
``_run_agent``; ``tests/test_cli_conversation.py`` covers it end to end. These
tests pin which directory and session a continuation lands in.
"""

from __future__ import annotations

from pathlib import Path

from cli import _legacy
from src.agent.trace import TraceWriter


def test_repeated_continue_reads_and_appends_one_canonical_trace(
    tmp_path, monkeypatch
) -> None:
    """Every continuation of a session lands in that session's trace directory."""
    runs_dir = tmp_path / "runs"
    sessions_dir = tmp_path / "sessions"
    trace_dir = sessions_dir / "session-1"

    writer = TraceWriter(trace_dir)
    writer.write({"type": "start", "prompt": "initial question"})
    writer.write({"type": "answer", "content": "initial answer"})
    writer.close()

    seen = []

    def fake_run_agent(prompt, run_dir_override, **kwargs):
        # The caller no longer builds a history: ``_run_agent`` replays it.
        assert "history" not in kwargs
        seen.append((prompt, run_dir_override, kwargs["session_id"]))
        continuation = TraceWriter(Path(run_dir_override))
        continuation.write({"type": "start", "prompt": prompt})
        continuation.write({"type": "answer", "content": f"answer to {prompt}"})
        continuation.close()
        return {"status": "success", "run_id": "session-1", "run_dir": run_dir_override}

    monkeypatch.setattr(_legacy, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(_legacy, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(_legacy, "_run_agent", fake_run_agent)
    monkeypatch.setattr(_legacy, "_print_json_result", lambda result: None)

    assert (
        _legacy.cmd_continue("session-1", "first follow-up", 5, json_mode=True)
        == _legacy.EXIT_SUCCESS
    )
    assert (
        _legacy.cmd_continue("session-1", "second follow-up", 5, json_mode=True)
        == _legacy.EXIT_SUCCESS
    )

    assert seen == [
        ("first follow-up", str(trace_dir), "session-1"),
        ("second follow-up", str(trace_dir), "session-1"),
    ]
    assert not (runs_dir / "session-1").exists()
