from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from src.research_protocol.ledger import TrialLedger
from src.research_protocol.trial import TrialEventType

from .test_protocol_hash import GOLDEN_PROTOCOL_HASH


def test_trial_ledger_concurrent_appends_do_not_fork(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite"

    def append_one(index: int):
        return TrialLedger(path).append(
            protocol_hash=GOLDEN_PROTOCOL_HASH,
            event_type=TrialEventType.TOOL_CALLED,
            payload={"index": index},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        events = list(pool.map(append_one, range(32)))

    sequences = sorted(event.sequence_number for event in events)
    assert sequences == list(range(1, 33))
    assert TrialLedger(path).verify().valid is True


def test_trial_ledger_concurrent_appends_do_not_lose_events_100(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite"

    def append_one(index: int):
        return TrialLedger(path).append(
            protocol_hash=GOLDEN_PROTOCOL_HASH,
            event_type=TrialEventType.POLICY_DECISION_RECORDED,
            payload={"policy_decision_id": f"pd_{index}"},
        )

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(append_one, range(100)))

    verification = TrialLedger(path).verify()
    assert verification.valid is True
    assert verification.event_count == 100


def test_sqlite_locked_retries(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite"
    ledger = TrialLedger(path, write_retry_count=8, write_retry_delay_ms=20)
    blocker = sqlite3.connect(path, timeout=0.1, check_same_thread=False)
    blocker.execute("BEGIN IMMEDIATE")

    def release_lock() -> None:
        blocker.rollback()
        blocker.close()

    timer = threading.Timer(0.08, release_lock)
    timer.start()
    try:
        event = ledger.append(
            protocol_hash=GOLDEN_PROTOCOL_HASH,
            event_type=TrialEventType.TRIAL_STARTED,
            payload={"trial_id": "retry"},
        )
    finally:
        timer.cancel()
        try:
            blocker.close()
        except sqlite3.Error:
            pass

    assert event.sequence_number == 1
    assert ledger.verify().valid is True


def test_trial_ledger_append_closes_success_connection(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "ledger.sqlite"
    ledger = TrialLedger(path)

    class _Cursor:
        def fetchone(self) -> None:
            return None

    class _SuccessConnection:
        def __init__(self) -> None:
            self.closed = False
            self.committed = False
            self.rolled_back = False

        def execute(self, _sql: str, _params: Any = None) -> _Cursor:
            return _Cursor()

        def commit(self) -> None:
            self.committed = True

        def rollback(self) -> None:
            self.rolled_back = True

        def close(self) -> None:
            self.closed = True

    conn = _SuccessConnection()
    monkeypatch.setattr(ledger, "_connect", lambda timeout=30.0: conn)

    event = ledger.append(
        protocol_hash=GOLDEN_PROTOCOL_HASH,
        event_type=TrialEventType.TRIAL_STARTED,
        payload={"trial_id": "success-close"},
    )

    assert event.sequence_number == 1
    assert conn.committed is True
    assert conn.rolled_back is False
    assert conn.closed is True


def test_trial_ledger_append_closes_each_locked_retry_on_terminal_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "ledger.sqlite"
    ledger = TrialLedger(path, write_retry_count=3, write_retry_delay_ms=0)

    class _LockedConnection:
        def __init__(self) -> None:
            self.closed = False
            self.rolled_back = False

        def execute(self, _sql: str, _params: Any = None) -> None:
            raise sqlite3.OperationalError("database is locked")

        def rollback(self) -> None:
            self.rolled_back = True

        def close(self) -> None:
            self.closed = True

    conns: list[_LockedConnection] = []

    def connect(*, timeout: float = 30.0) -> _LockedConnection:
        del timeout
        conn = _LockedConnection()
        conns.append(conn)
        return conn

    monkeypatch.setattr(ledger, "_connect", connect)
    monkeypatch.setattr("src.research_protocol.ledger.time.sleep", lambda _delay: None)
    monkeypatch.setattr("src.research_protocol.ledger.random.uniform", lambda _low, _high: 0.0)

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        ledger.append(
            protocol_hash=GOLDEN_PROTOCOL_HASH,
            event_type=TrialEventType.TRIAL_STARTED,
            payload={"trial_id": "terminal-locked"},
        )

    assert len(conns) == 3
    assert all(conn.rolled_back for conn in conns)
    assert all(conn.closed for conn in conns)
