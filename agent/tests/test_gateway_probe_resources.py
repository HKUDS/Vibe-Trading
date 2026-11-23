"""Probe instrumentation must not leave catalog connections for cyclic GC."""

from pathlib import Path
import sqlite3

import pytest


@pytest.mark.parametrize("broken", [False, True])
def test_snapshot_closes_sqlite_even_when_query_fails(tmp_path, monkeypatch, broken):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    from gateway_minute_restart_probe import snapshot

    directory = tmp_path / "history"
    directory.mkdir()
    connection = sqlite3.connect(directory / "catalog.sqlite")
    connection.execute("CREATE TABLE jobs(id TEXT)")
    if not broken:
        connection.execute("CREATE TABLE chunks(job TEXT,idx INTEGER)")
    connection.commit()
    connection.close()
    original = sqlite3.connect
    observed = []

    def connect(*args, **kwargs):
        db = original(*args, **kwargs)
        observed.append(db)
        return db

    monkeypatch.setattr(sqlite3, "connect", connect)
    if broken:
        with pytest.raises(sqlite3.OperationalError):
            snapshot(tmp_path)
    else:
        assert snapshot(tmp_path) == ([], [])
    assert len(observed) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        observed[0].execute("SELECT 1")
