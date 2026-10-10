"""Unreadable UTF-8 records must not hide intact saved-session records."""

from pathlib import Path

import pytest

from src.session.models import Attempt, Message, Session
from src.session.store import SessionStore


@pytest.mark.parametrize("bad_bytes", [b'\xff', b'{"title":"\xe4\xb8"}'])
def test_bad_session_encoding_keeps_order_limit_and_original_bytes(
    tmp_path: Path, caplog, bad_bytes: bytes
) -> None:
    store = SessionStore(tmp_path / "sessions")
    store.create_session(Session(session_id="older", updated_at="2026-01-01"))
    store.create_session(Session(session_id="newer", updated_at="2026-01-02"))
    path = store._session_file("broken")
    path.parent.mkdir()
    path.write_bytes(bad_bytes)

    assert [s.session_id for s in store.list_sessions()] == ["newer", "older"]
    assert [s.session_id for s in store.list_sessions(limit=1)] == ["newer"]
    assert store.get_session("broken") is None
    assert path.read_bytes() == bad_bytes
    assert "Skipping corrupt JSON" in caplog.text


@pytest.mark.parametrize("bad_bytes", [b'\xff', b'{"prompt":"\xe4\xb8"}'])
def test_bad_attempt_encoding_keeps_siblings_and_original_bytes(
    tmp_path: Path, caplog, bad_bytes: bytes
) -> None:
    store = SessionStore(tmp_path / "sessions")
    store.create_session(Session(session_id="sample"))
    store.create_attempt(Attempt(session_id="sample", attempt_id="intact"))
    path = store._attempt_file("sample", "broken")
    path.parent.mkdir()
    path.write_bytes(bad_bytes)

    assert [a.attempt_id for a in store.list_attempts()] == ["intact"]
    assert store.get_attempt("sample", "broken") is None
    assert path.read_bytes() == bad_bytes
    assert "Skipping corrupt JSON" in caplog.text


@pytest.mark.parametrize("bad_line", [b'{"content":"\xff"}\n', b'\xe4\xb8\r\n'])
def test_bad_message_encoding_preserves_neighbors_limits_and_original_bytes(
    tmp_path: Path, caplog, bad_line: bytes
) -> None:
    store = SessionStore(tmp_path / "sessions")
    store.create_session(Session(session_id="sample"))
    store.append_message(Message(session_id="sample", content="之前 😀"))
    path = store._messages_file("sample")
    with path.open("ab") as log:
        log.write(bad_line)
    store.append_message(Message(session_id="sample", content="之后 café"))
    original = path.read_bytes()

    assert [m.content for m in store.get_messages("sample")] == [
        "之前 😀", "之后 café"
    ]
    assert [m.content for m in store.get_messages("sample", limit=1)] == [
        "之后 café"
    ]
    assert path.read_bytes() == original
    assert "Skipping corrupted message" in caplog.text
