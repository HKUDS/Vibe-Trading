"""Tests for Phase 2 source-level circuit breaker."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import src.reliability.data.circuit_breaker as circuit_breaker_module
from src.reliability.data.circuit_breaker import CircuitBreaker


def test_circuit_breaker_opens_after_three_failures(tmp_path: Path) -> None:
    breaker = CircuitBreaker(tmp_path / "breaker.sqlite", failure_threshold=3, open_seconds=60)

    for _ in range(3):
        breaker.record_failure("yahoo", RuntimeError("rate limited"))

    assert breaker.snapshot("yahoo").state == "OPEN"


def test_circuit_breaker_half_open_success_closes(tmp_path: Path) -> None:
    breaker = CircuitBreaker(tmp_path / "breaker.sqlite", failure_threshold=1, open_seconds=0)
    breaker.record_failure("stooq", RuntimeError("timeout"))

    assert breaker.before_request("stooq").state == "HALF_OPEN"
    breaker.record_success("stooq")

    assert breaker.snapshot("stooq").state == "CLOSED"


def test_circuit_breaker_skip_records_warning(tmp_path: Path) -> None:
    breaker = CircuitBreaker(tmp_path / "breaker.sqlite", failure_threshold=1, open_seconds=60)
    breaker.record_failure("finnhub", RuntimeError("quota"))

    decision = breaker.before_request("finnhub")

    assert decision.allowed is False
    assert decision.warning is not None
    assert decision.warning.code == "DATA_SOURCE_SKIPPED_BY_CIRCUIT"


def test_record_failure_is_atomic_for_concurrent_new_source(tmp_path: Path, monkeypatch) -> None:
    worker_count = 12
    breaker = CircuitBreaker(
        tmp_path / "breaker.sqlite",
        failure_threshold=worker_count,
        open_seconds=60,
    )
    original_snapshot = breaker.snapshot
    barrier = threading.Barrier(worker_count)

    def stale_snapshot(source: str):
        snapshot = original_snapshot(source)
        barrier.wait(timeout=5)
        return snapshot

    monkeypatch.setattr(breaker, "snapshot", stale_snapshot)

    def fail_once(_index: int) -> None:
        breaker.record_failure("new_source", RuntimeError("boom"))

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        list(pool.map(fail_once, range(worker_count)))

    snapshot = original_snapshot("new_source")
    assert snapshot.consecutive_failures == worker_count
    assert snapshot.state == "OPEN"


def test_circuit_breaker_connections_close_for_operations(tmp_path: Path, monkeypatch) -> None:
    real_connect = sqlite3.connect
    opened: list["_TrackingConnection"] = []

    class _TrackingConnection:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._conn = real_connect(*args, **kwargs)
            self.closed = False

        def __getattr__(self, name: str) -> Any:
            return getattr(self._conn, name)

        def __enter__(self) -> "_TrackingConnection":
            self._conn.__enter__()
            return self

        def __exit__(self, *args: Any) -> bool | None:
            return self._conn.__exit__(*args)

        def close(self) -> None:
            self.closed = True
            self._conn.close()

    def tracking_connect(*args: Any, **kwargs: Any) -> _TrackingConnection:
        conn = _TrackingConnection(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(circuit_breaker_module.sqlite3, "connect", tracking_connect)

    breaker = CircuitBreaker(tmp_path / "breaker.sqlite", failure_threshold=2, open_seconds=0)
    breaker.record_failure("yahoo", RuntimeError("rate limited"))
    breaker.before_request("yahoo")
    breaker.record_success("yahoo")
    breaker.snapshot("yahoo")

    assert opened
    assert all(conn.closed for conn in opened)
