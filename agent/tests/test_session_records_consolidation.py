"""Regression coverage for the thread-backed record projections."""

from __future__ import annotations

from pathlib import Path

from src.session.checkpoint import ResponseCheckpoint
from src.session.models import Attempt, Session
from src.session.runtime import SessionRuntime
from src.session.store import SessionStore
from src.session.thread import ThreadLog, replay


def _call(call_id: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "lookup", "arguments": '{"key":"us"}'},
    }


def test_replay_applies_recorded_microcompact_and_collapse_views(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append("turn_start", "t1", prompt="q")
    log.append("user", "t1", content="q", llm_content="q")
    assistant = log.append("assistant", "t1", content="", tool_calls=[_call("c1")])
    result = log.append(
        "tool_result", "t1", tool_call_id="c1", name="lookup", content="full result", status="ok"
    )
    collapsed = {
        "role": "tool",
        "tool_call_id": "c1",
        "name": "lookup",
        "content": "[CLEARED FROM CONTEXT]",
    }
    log.append(
        "compaction", "t1", summary="", replaces_through_seq=0, layer=1,
        changes=[{"seq": result.seq, "message": collapsed}],
    )
    compacted_call = {**_call("c1"), "function": {"name": "lookup", "arguments": "{}"}}
    log.append(
        "compaction", "t1", summary="", replaces_through_seq=0, layer=2,
        changes=[{"seq": assistant.seq, "message": {"role": "assistant", "content": "", "tool_calls": [compacted_call]}}],
    )

    messages = replay(log.read())

    assert messages[1]["tool_calls"][0]["function"]["arguments"] == "{}"
    assert messages[2]["content"] == "[CLEARED FROM CONTEXT]"
    assert not any(item.type == "compaction" and item.get("layer") == 3 for item in log.read())


def test_stream_checkpoint_is_thread_backed_for_new_sessions(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create_session(Session(title="checkpoint"))
    runtime = SessionRuntime(store.thread_log(session.session_id), session.session_id)
    attempt = Attempt(session_id=session.session_id, prompt="write")
    recorder = runtime.begin_turn(attempt.attempt_id)
    recorder.start(prompt="write", message={"role": "user", "content": "write"}, model=None, provider=None)
    checkpoint = ResponseCheckpoint(store, attempt, runtime=runtime, min_interval_seconds=0)
    checkpoint.handle_event('item.delta', {"kind": 'text.delta', 'delta': 'partial'})
    checkpoint.flush()

    assert runtime.partial_response(attempt.attempt_id) == "partial"
    assert not (tmp_path / "sessions" / session.session_id / "attempts" / attempt.attempt_id / "partial_response.json").exists()
    assert any(item.type == "checkpoint" for item in runtime.thread.read())


def test_loop_compaction_projection_calls_thread_sink() -> None:
    from types import SimpleNamespace

    from src.agent.loop import AgentLoop

    calls: list[tuple[int, list[dict]]] = []
    loop = object.__new__(AgentLoop)
    loop._thread = SimpleNamespace(
        compaction_layer=lambda layer, messages: calls.append((layer, messages)),
        seq_of=lambda message: 1,
    )
    current = {"role": "tool", "tool_call_id": "c1", "content": "after"}
    loop._record_compaction_layer([current], 1, [{"role": "tool", "tool_call_id": "c1", "content": "before"}])

    assert calls == [(1, [current])]

