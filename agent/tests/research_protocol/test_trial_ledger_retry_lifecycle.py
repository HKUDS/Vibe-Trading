"""TrialLedger retry connection lifecycle regression tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.research_protocol.ledger import TrialLedger


def test_append_connection_closes_on_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    closed = {"count": 0}
    original_connect = sqlite3.connect

    class ConnProxy:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self.conn = conn

        def __getattr__(self, name: str):
            return getattr(self.conn, name)

        def close(self) -> None:
            closed["count"] += 1
            self.conn.close()

    monkeypatch.setattr("src.research_protocol.ledger.sqlite3.connect", lambda *a, **k: ConnProxy(original_connect(*a, **k)))

    TrialLedger(tmp_path / "trial.sqlite").append({"trial_id": "t1"})

    assert closed["count"] >= 1


def test_append_connection_closes_on_terminal_locked_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    closed = {"count": 0}

    class LockedConn:
        def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise sqlite3.OperationalError("database is locked")

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            closed["count"] += 1

    monkeypatch.setattr("src.research_protocol.ledger.sqlite3.connect", lambda *a, **k: LockedConn())

    with pytest.raises(sqlite3.OperationalError):
        TrialLedger(tmp_path / "trial.sqlite", max_attempts=2, sleep_seconds=0).append({"trial_id": "t1"})

    assert closed["count"] == 2


def test_retry_sleep_does_not_hold_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_connect = sqlite3.connect
    state = {"attempt": 0, "open": 0, "slept_with_open": False}

    class FlakyConn:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self.conn = conn
            state["open"] += 1

        def __getattr__(self, name: str):
            return getattr(self.conn, name)

        def execute(self, sql, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            if "INSERT INTO trial_ledger" in sql and state["attempt"] == 0:
                state["attempt"] += 1
                raise sqlite3.OperationalError("database is locked")
            return self.conn.execute(sql, *args, **kwargs)

        def close(self) -> None:
            state["open"] -= 1
            self.conn.close()

    def fake_sleep(seconds: float) -> None:
        del seconds
        state["slept_with_open"] = state["open"] > 0

    monkeypatch.setattr("src.research_protocol.ledger.sqlite3.connect", lambda *a, **k: FlakyConn(original_connect(*a, **k)))
    monkeypatch.setattr("src.research_protocol.ledger.time.sleep", fake_sleep)

    TrialLedger(tmp_path / "trial.sqlite", max_attempts=2, sleep_seconds=0.001).append({"trial_id": "t1"})

    assert state["slept_with_open"] is False


def test_hash_chain_unchanged_after_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_connect = sqlite3.connect
    state = {"attempt": 0}

    class FlakyConn:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self.conn = conn

        def __getattr__(self, name: str):
            return getattr(self.conn, name)

        def execute(self, sql, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            if "INSERT INTO trial_ledger" in sql and state["attempt"] == 0:
                state["attempt"] += 1
                raise sqlite3.OperationalError("database is locked")
            return self.conn.execute(sql, *args, **kwargs)

        def close(self) -> None:
            self.conn.close()

    ledger = TrialLedger(tmp_path / "trial.sqlite", max_attempts=2, sleep_seconds=0)
    first_hash = ledger.append({"trial_id": "t0"})
    monkeypatch.setattr("src.research_protocol.ledger.sqlite3.connect", lambda *a, **k: FlakyConn(original_connect(*a, **k)))
    second_hash = ledger.append({"trial_id": "t1"})

    events = ledger.list_events()
    assert [event["event_hash"] for event in events] == [first_hash, second_hash]
    assert events[1]["previous_hash"] == first_hash
