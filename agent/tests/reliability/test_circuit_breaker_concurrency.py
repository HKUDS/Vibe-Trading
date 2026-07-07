"""Circuit breaker SQLite lifecycle and concurrency security tests."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.reliability.data.circuit_breaker import CircuitBreakerStore


def test_record_failure_closes_connection_on_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr("src.reliability.data.circuit_breaker.sqlite3.connect", lambda *a, **k: ConnProxy(original_connect(*a, **k)))

    CircuitBreakerStore(tmp_path / "cb.sqlite").record_failure("alpha")

    assert closed["count"] >= 1


def test_record_failure_closes_connection_on_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    closed = {"count": 0}

    class BrokenConn:
        def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise sqlite3.OperationalError("boom")

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            closed["count"] += 1

    monkeypatch.setattr("src.reliability.data.circuit_breaker.sqlite3.connect", lambda *a, **k: BrokenConn())

    with pytest.raises(sqlite3.OperationalError):
        CircuitBreakerStore(tmp_path / "cb.sqlite").record_failure("alpha")

    assert closed["count"] == 1


def test_concurrent_failures_are_atomic(tmp_path: Path) -> None:
    store = CircuitBreakerStore(tmp_path / "cb.sqlite")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: store.record_failure("alpha"), range(80)))

    assert store.get_failure_count("alpha") == 80


def test_new_source_concurrent_failures_no_lost_update(tmp_path: Path) -> None:
    store = CircuitBreakerStore(tmp_path / "cb.sqlite")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: store.record_failure("new-source"), range(40)))

    assert store.get_failure_count("new-source") == 40


def test_rollback_releases_lock_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = CircuitBreakerStore(tmp_path / "cb.sqlite")
    original_connect = sqlite3.connect

    class FailingInsertConn:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self.conn = conn

        def __getattr__(self, name: str):
            return getattr(self.conn, name)

        def execute(self, sql, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            if "INSERT INTO circuit_breaker_failures" in sql:
                raise sqlite3.OperationalError("injected failure")
            return self.conn.execute(sql, *args, **kwargs)

        def close(self) -> None:
            self.conn.close()

    monkeypatch.setattr(
        "src.reliability.data.circuit_breaker.sqlite3.connect",
        lambda *a, **k: FailingInsertConn(original_connect(*a, **k)),
    )
    with pytest.raises(sqlite3.OperationalError):
        store.record_failure("alpha")

    monkeypatch.setattr("src.reliability.data.circuit_breaker.sqlite3.connect", original_connect)
    store.record_failure("alpha")
    assert store.get_failure_count("alpha") == 1
