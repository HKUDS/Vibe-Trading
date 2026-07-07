from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.research_protocol.ledger import TrialLedger
from src.research_protocol.trial import TrialEventType

from .test_protocol_hash import GOLDEN_PROTOCOL_HASH


def test_trial_ledger_append_creates_linear_hash_chain(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.sqlite")

    first = ledger.append(
        protocol_hash=GOLDEN_PROTOCOL_HASH,
        event_type=TrialEventType.PROTOCOL_REGISTERED,
        payload={"protocol_id": "proto_fixture"},
    )
    second = ledger.append(
        protocol_hash=GOLDEN_PROTOCOL_HASH,
        event_type=TrialEventType.TRIAL_STARTED,
        payload={"trial_id": "trial_1"},
    )

    assert first.sequence_number == 1
    assert second.sequence_number == 2
    assert first.previous_event_hash is None
    assert second.previous_event_hash == first.event_hash
    assert ledger.verify().valid is True
    assert ledger.verify().event_count == 2


def test_trial_ledger_verify_detects_tamper(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.sqlite")
    event = ledger.append(
        protocol_hash=GOLDEN_PROTOCOL_HASH,
        event_type=TrialEventType.TRIAL_STARTED,
        payload={"trial_id": "trial_1"},
    )

    with sqlite3.connect(tmp_path / "ledger.sqlite") as conn:
        conn.execute(
            "UPDATE trial_events SET payload_json = ? WHERE event_id = ?",
            (json.dumps({"trial_id": "tampered"}, sort_keys=True), event.event_id),
        )

    result = ledger.verify()
    assert result.valid is False
    assert any("event_hash" in error for error in result.errors)
