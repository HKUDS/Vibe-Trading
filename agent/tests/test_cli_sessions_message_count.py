"""Regression: the --sessions table's Messages column must show the real
total, not get_messages' default limit=100 chat-history slice.
"""

from __future__ import annotations

import cli._legacy as legacy
from src.session.models import Message, Session
from src.session.store import SessionStore


def test_sessions_table_reports_the_full_message_count_past_the_default_limit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(legacy, "SESSIONS_DIR", tmp_path)
    store = SessionStore(base_dir=tmp_path)
    session = Session(title="long chat")
    store.create_session(session)
    for i in range(150):
        store.append_message(
            Message(session_id=session.session_id, role="user" if i % 2 == 0 else "assistant", content=f"message {i}")
        )

    legacy.cmd_sessions()

    out = capsys.readouterr().out
    assert "150" in out
    assert "100" not in out


def test_sessions_table_still_reports_a_short_session_correctly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(legacy, "SESSIONS_DIR", tmp_path)
    store = SessionStore(base_dir=tmp_path)
    session = Session(title="short chat")
    store.create_session(session)
    store.append_message(Message(session_id=session.session_id, role="user", content="hi"))
    store.append_message(Message(session_id=session.session_id, role="assistant", content="hello"))

    legacy.cmd_sessions()

    out = capsys.readouterr().out
    assert "2" in out
