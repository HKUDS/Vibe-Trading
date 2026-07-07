from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
