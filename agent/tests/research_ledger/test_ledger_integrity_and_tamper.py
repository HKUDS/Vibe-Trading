from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.research_ledger.trial_ledger import TrialLedger, TrialLedgerAppendError, TrialLedgerEntry


def _entry(trial_id: str, status: str = "success") -> TrialLedgerEntry:
    return TrialLedgerEntry(
        trial_id=trial_id,
        trial_group_id="group",
        parent_trial_id=None,
        candidate_id="candidate",
        parent_seed_id=None,
        formula="rank(close)",
        formula_hash="sha256:formula",
        data_snapshot_hash="sha256:snapshot",
        universe_hash="sha256:universe",
        split_id="train_valid",
        data_scope="train_valid",
        search_space_hash="sha256:space",
        objective="objective",
        random_seed=1,
        n_candidates_seen_so_far=1,
        status=status,  # type: ignore[arg-type]
        decision="research_only",
        reason_codes=[],
        metrics_summary={"rank_ic": 0.01},
        previous_entry_hash=None,
        entry_hash="",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
    )


def test_ledger_records_all_terminal_statuses(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.sqlite")
    for status in ("success", "reject", "skip", "error"):
        ledger.append(_entry(f"trial-{status}", status))

    assert [entry.status for entry in ledger.query()] == ["success", "reject", "skip", "error"]
    assert ledger.verify_hash_chain()


def test_ledger_hash_chain_detects_payload_tampering(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    ledger = TrialLedger(db_path)
    ledger.append(_entry("trial-1"))

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload FROM trial_entries WHERE trial_id = 'trial-1'").fetchone()
        payload = json.loads(row[0])
        payload["metrics_summary"]["rank_ic"] = 0.99
        conn.execute(
            "UPDATE trial_entries SET payload = ? WHERE trial_id = 'trial-1'",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
        )

    assert not ledger.verify_hash_chain()


def test_duplicate_trial_id_is_rejected(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.sqlite")
    ledger.append(_entry("trial-1"))

    with pytest.raises(TrialLedgerAppendError):
        ledger.append(_entry("trial-1"))
