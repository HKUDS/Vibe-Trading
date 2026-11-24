"""An existing REPLACE-corrupted FTS index must recover on upgrade."""

import sqlite3

import pytest

from src.memory.search_index import MemorySearchIndex


def _legacy_index(path):
    index = MemorySearchIndex(db_path=path)
    conn = index._get_conn()
    conn.execute("PRAGMA user_version=0")
    for entry_id, body in [("old", "copper futures"), ("old", "gold digest")]:
        conn.execute(
            "INSERT OR REPLACE INTO memories(id, body) VALUES (?, ?)",
            (entry_id, body),
        )
    conn.execute("DELETE FROM memories WHERE id='old'")
    conn.execute("INSERT INTO memories(id, body) VALUES ('new', 'bond notes')")
    conn.commit()
    assert [m.entry_id for m in index.search("copper")] == ["new"]
    index.close()


def test_open_repairs_existing_false_positive_and_preserves_content(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_index(path)
    index = MemorySearchIndex(db_path=path)
    try:
        assert index.search("copper") == []
        assert [m.entry_id for m in index.search("bond")] == ["new"]
        index._get_conn().execute(
            "INSERT INTO memories_fts(memories_fts, rank) VALUES ('integrity-check', 1)"
        )
    finally:
        index.close()


def test_failed_upgrade_does_not_serve_stale_hits_and_retries_on_reopen(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    _legacy_index(path)
    original = sqlite3.connect

    class FailRebuild(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if "VALUES ('rebuild')" in sql:
                raise sqlite3.OperationalError("injected rebuild failure")
            return super().execute(sql, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", lambda *a, **k: original(*a, factory=FailRebuild, **k))
        index = MemorySearchIndex(db_path=path)
        try:
            assert index.search("copper") == []
            assert index._get_conn().execute("PRAGMA user_version").fetchone()[0] == 0
        finally:
            index.close()
    index = MemorySearchIndex(db_path=path)
    try:
        assert index.search("copper") == []
        assert [m.entry_id for m in index.search("bond")] == ["new"]
    finally:
        index.close()


def test_current_index_does_not_rebuild_on_every_open(tmp_path, monkeypatch):
    path = tmp_path / "current.db"
    index = MemorySearchIndex(db_path=path)
    index.index_entry("entry", "title", "", "", "copper")
    index.close()
    original = sqlite3.connect

    class RejectRebuild(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if "VALUES ('rebuild')" in sql:
                pytest.fail("an already upgraded index was rebuilt again")
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: original(*a, factory=RejectRebuild, **k))
    index = MemorySearchIndex(db_path=path)
    try:
        assert [m.entry_id for m in index.search("copper")] == ["entry"]
    finally:
        index.close()
