"""Regression: the --sessions table's Messages column must show the real
total, not get_messages' default limit=100 chat-history slice.
"""

from __future__ import annotations

from cli.commands import common
from cli.commands import sessions as legacy
from src.session.models import Session
from src.session.store import SessionStore


def test_sessions_table_reports_the_full_message_count_past_the_default_limit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(common, "SESSIONS_DIR", tmp_path)
    store = SessionStore(base_dir=tmp_path)
    session = Session(title="long chat")
    store.create_session(session)
    thread = store.thread_log(session.session_id)
    for i in range(75):
        turn = f"turn-{i}"
        thread.append("turn_start", turn, prompt=f"message {2 * i}")
        thread.append("user", turn, content=f"message {2 * i}", llm_content=f"message {2 * i}")
        thread.append("assistant", turn, content=f"message {2 * i + 1}", phase="final")
        thread.append("turn_end", turn, status="completed")

    legacy.cmd_sessions()

    out = capsys.readouterr().out
    assert "150" in out
    assert "100" not in out


def test_sessions_table_still_reports_a_short_session_correctly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(common, "SESSIONS_DIR", tmp_path)
    store = SessionStore(base_dir=tmp_path)
    session = Session(title="short chat")
    store.create_session(session)
    thread = store.thread_log(session.session_id)
    thread.append("turn_start", "turn-1", prompt="hi")
    thread.append("user", "turn-1", content="hi", llm_content="hi")
    thread.append("assistant", "turn-1", content="hello", phase="final")
    thread.append("turn_end", "turn-1", status="completed")

    legacy.cmd_sessions()

    out = capsys.readouterr().out
    assert "2" in out
