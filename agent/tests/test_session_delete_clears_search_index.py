"""Deleting a session must purge its text from the always-on search index."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config

from tests.recording_helpers import seed_message

import json
import sqlite3

import pytest
from src.session.events import EventBus
from src.session.models import Message
from src.session.search import SessionSearchIndex
from src.session.models import SessionBusyError
from src.session.service import SessionService
from src.session.store import SessionStore
from src.tools.session_search_tool import SessionSearchTool

DELETED_TERM = "vegacarry"
SIBLING_TERM = "gammascalp"


@pytest.fixture
def owned_delete_index(tmp_path, monkeypatch):
    """Real service, real index, real search tool over one owned database."""
    index = SessionSearchIndex(tmp_path / "search.db")
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: index)
    monkeypatch.setattr("src.session.search.get_shared_index", lambda: index)
    service = SessionService(
        policy=ToolPolicy.from_config(get_env_config()),
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(),
        runs_dir=tmp_path / "runs",
    )
    doomed = service.create_session(title="Volatility carry study")
    sibling = service.create_session(title="Unrelated conversation")
    # Messages are admitted straight to the store and index so fixture setup
    # never invokes an agent or a model provider.
    for session, text in (
        (doomed, f"my secret thesis: short {DELETED_TERM} into earnings"),
        (sibling, f"unrelated {SIBLING_TERM} notes"),
    ):
        seed_message(service.store, Message(session_id=session.session_id, role="user", content=text))
        index.index_message(session.session_id, "user", text)
    try:
        yield service, index, doomed, sibling
    finally:
        index.close()


def _search_session_ids(query: str) -> list[str]:
    reply = json.loads(SessionSearchTool().execute(query=query))
    assert reply["status"] == "ok", reply
    return [match["session_id"] for match in reply["results"]]


def _index_rows(index: SessionSearchIndex, session_id: str) -> tuple[int, int]:
    conn = index._get_conn()
    sessions = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()[0]
    messages = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
    ).fetchone()[0]
    return sessions, messages


def _fts_hits(index: SessionSearchIndex, term: str) -> int:
    return index._get_conn().execute(
        "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH ?",
        (f'"{term}"',),
    ).fetchone()[0]


def test_deleted_session_text_is_no_longer_searchable(owned_delete_index):
    service, index, doomed, sibling = owned_delete_index
    assert _search_session_ids(DELETED_TERM) == [doomed.session_id]

    assert service.delete_session(doomed.session_id) is True

    assert service.store.get_session(doomed.session_id) is None
    assert _search_session_ids(DELETED_TERM) == []
    assert _fts_hits(index, DELETED_TERM) == 0
    assert _index_rows(index, doomed.session_id) == (0, 0)


def test_delete_leaves_an_unrelated_session_fully_indexed(owned_delete_index):
    service, index, doomed, sibling = owned_delete_index

    assert service.delete_session(doomed.session_id) is True

    assert _search_session_ids(SIBLING_TERM) == [sibling.session_id]
    assert _fts_hits(index, SIBLING_TERM) == 1
    assert _index_rows(index, sibling.session_id) == (1, 1)
    assert (
        index._get_conn()
        .execute("SELECT title FROM sessions WHERE id = ?", (sibling.session_id,))
        .fetchone()[0]
        == "Unrelated conversation"
    )


def test_delete_keeps_the_session_for_retry_when_search_is_unavailable(
    owned_delete_index, monkeypatch
):
    """A failed purge must not claim that the private text was deleted."""
    service, index, doomed, _sibling = owned_delete_index

    def _boom(session_id: str) -> None:
        raise RuntimeError("index offline")

    monkeypatch.setattr(index, "remove_session", _boom, raising=False)

    with pytest.raises(RuntimeError, match="index offline"):
        service.delete_session(doomed.session_id)
    assert service.store.get_session(doomed.session_id) is not None


def test_purge_transaction_rolls_back_and_a_retry_succeeds(owned_delete_index):
    service, index, doomed, _ = owned_delete_index
    conn = index._get_conn()
    conn.execute("CREATE TRIGGER block_delete BEFORE DELETE ON sessions "
                 "BEGIN SELECT RAISE(ABORT, 'purge failed'); END")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="purge failed"):
        service.delete_session(doomed.session_id)
    assert service.store.get_session(doomed.session_id) is not None
    assert _index_rows(index, doomed.session_id) == (1, 1)
    assert _fts_hits(index, DELETED_TERM) == 1
    conn.execute("DROP TRIGGER block_delete")
    conn.commit()
    assert service.delete_session(doomed.session_id) is True
    assert _fts_hits(index, DELETED_TERM) == 0


def test_missing_directory_still_clears_orphaned_index_rows(owned_delete_index):
    service, index, doomed, _ = owned_delete_index
    service.store.delete_session(doomed.session_id)
    assert service.delete_session(doomed.session_id) is False
    assert _index_rows(index, doomed.session_id) == (0, 0)
    assert _fts_hits(index, DELETED_TERM) == 0


def test_active_run_cannot_recreate_deleted_content(owned_delete_index):
    service, index, doomed, _ = owned_delete_index
    service._reserve_session(doomed.session_id)
    try:
        with pytest.raises(SessionBusyError):
            service.delete_session(doomed.session_id)
        assert service.store.get_session(doomed.session_id) is not None
        assert _fts_hits(index, DELETED_TERM) == 1
    finally:
        service._release_session(doomed.session_id)
    assert service.delete_session(doomed.session_id) is True


def test_http_delete_reports_conflict_for_an_active_run(owned_delete_index, monkeypatch):
    from fastapi.testclient import TestClient
    import api_server

    service, _, doomed, _ = owned_delete_index
    monkeypatch.setattr(api_server, "_session_service", service)
    service._reserve_session(doomed.session_id)
    try:
        client = TestClient(api_server.app, client=("127.0.0.1", 50000))
        response = client.delete(f"/sessions/{doomed.session_id}")
        assert response.status_code == 409
        assert service.store.get_session(doomed.session_id) is not None
    finally:
        service._release_session(doomed.session_id)
