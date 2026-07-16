"""Regression tests for continuing a persisted CLI conversation."""

from __future__ import annotations

from pathlib import Path

from cli import _legacy
from src.agent.trace import TraceWriter


def test_repeated_continue_reads_and_appends_one_canonical_trace(
    tmp_path, monkeypatch
) -> None:
    """A session continuation must remain visible to the next continuation."""
    runs_dir = tmp_path / "runs"
    sessions_dir = tmp_path / "sessions"
    trace_dir = sessions_dir / "session-1"

    writer = TraceWriter(trace_dir)
    writer.write({"type": "start", "prompt": "initial question"})
    writer.write({"type": "answer", "content": "initial answer"})
    writer.close()

    histories = []

    def fake_run_agent(prompt, history, run_dir_override, **kwargs):
        histories.append(list(history))
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

    assert histories[0] == [
        {"role": "user", "content": "initial question"},
        {"role": "assistant", "content": "initial answer"},
    ]
    assert histories[1] == [
        *histories[0],
        {"role": "user", "content": "first follow-up"},
        {"role": "assistant", "content": "answer to first follow-up"},
    ]
    assert not (runs_dir / "session-1").exists()
