"""Schema-bad messages.jsonl lines must be skipped like JSONDecodeError lines."""

from __future__ import annotations

import json
from pathlib import Path

from src.session.models import Message, Session
from src.session.store import SessionStore


def _seed(store: SessionStore, session_id: str) -> Path:
    store.create_session(Session(session_id=session_id, title="t"))
    store.append_message(
        Message(session_id=session_id, role="user", content="keep-before")
    )
    return store._messages_file(session_id)


def test_get_messages_skips_non_object_json_and_keeps_siblings(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    sid = "abc123def456"
    path = _seed(store, sid)
    path.write_text(
        path.read_text(encoding="utf-8")
        + "null\n"
        + json.dumps(
            {
                "message_id": "2",
                "session_id": sid,
                "role": "user",
                "content": "keep-after",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    contents = [m.content for m in store.get_messages(sid)]
    assert contents == ["keep-before", "keep-after"]


def test_get_messages_skips_unexpected_keys_and_keeps_siblings(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    sid = "abc123def789"
    path = _seed(store, sid)
    path.write_text(
        path.read_text(encoding="utf-8")
        + json.dumps(
            {
                "message_id": "2",
                "session_id": sid,
                "role": "user",
                "content": "bad",
                "tool_calls": [],
            }
        )
        + "\n"
        + json.dumps(
            {
                "message_id": "3",
                "session_id": sid,
                "role": "user",
                "content": "keep-after",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    contents = [m.content for m in store.get_messages(sid)]
    assert contents == ["keep-before", "keep-after"]


def test_full_and_bounded_reads_count_only_valid_messages(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    sid = "limit-regression"
    path = _seed(store, sid)
    with path.open("a", encoding="utf-8") as log:
        for i in range(100):
            log.write(json.dumps({"session_id": sid, "role": "user", "content": str(i)}) + "\n")
        log.write("null\n")

    expected = [str(i) for i in range(100)]
    assert [m.content for m in store.get_messages(sid, None)] == ["keep-before", *expected]
    assert [m.content for m in store.get_messages(sid)] == expected
    assert [m.content for m in store.get_messages(sid, 1)] == ["99"]
    assert store.get_messages(sid, 0) == []
    assert store.get_messages(sid, -1) == []
