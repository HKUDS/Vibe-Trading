"""Corrupt thread rows must not hide neighboring projected messages."""
from __future__ import annotations
import json
from src.session.models import Session
from src.session.store import SessionStore


def _seed(store, session_id):
    store.create_session(Session(session_id=session_id, title="t"))
    log = store.thread_log(session_id)
    log.append("turn_start", "t", prompt="")
    log.append("user", "t", content="keep-before", llm_content="keep-before")
    return log.path


def _row(content, seq=4, **extra):
    return {"type": "user", "turn_id": "t", "seq": seq, "ts": 1, "content": content, "llm_content": content, **extra}


def test_get_messages_skips_non_object_json_and_keeps_siblings(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    path = _seed(store, "sample")
    with path.open("a") as stream:
        stream.write("null\n" + json.dumps(_row("keep-after")) + "\n")
    assert [m.content for m in store.get_messages("sample")] == ["keep-before", "keep-after"]


def test_get_messages_skips_unexpected_keys_and_keeps_siblings(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    path = _seed(store, "sample")
    with path.open("a") as stream:
        stream.write(json.dumps(_row("bad", tool_calls=[])) + "\n" + json.dumps(_row("keep-after", 5)) + "\n")
    assert [m.content for m in store.get_messages("sample")] == ["keep-before", "keep-after"]


def test_full_and_bounded_reads_count_only_valid_messages(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    path = _seed(store, "sample")
    with path.open("a") as stream:
        for i in range(100):
            stream.write(json.dumps(_row(str(i), i + 3)) + "\n")
        stream.write("null\n")
    expected = [str(i) for i in range(100)]
    assert [m.content for m in store.get_messages("sample", None)] == ["keep-before", *expected]
    assert [m.content for m in store.get_messages("sample")] == expected
    assert [m.content for m in store.get_messages("sample", 1)] == ["99"]
    assert store.get_messages("sample", 0) == []
    assert store.get_messages("sample", -1) == []
