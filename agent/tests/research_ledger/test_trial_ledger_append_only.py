from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.research_ledger.trial_ledger import (
    TrialLedger,
    TrialLedgerEntry,
    TrialLedgerMutationError,
)


def _entry(trial_id: str, *, status: str = "success") -> TrialLedgerEntry:
    return TrialLedgerEntry(
        trial_id=trial_id,
        trial_group_id="group",
        parent_trial_id=None,
        candidate_id=f"candidate-{trial_id}",
        parent_seed_id=None,
        formula="rank(close)",
        formula_hash="sha256:formula",
        data_snapshot_hash="sha256:snapshot",
        universe_hash="sha256:universe",
        split_id="train_valid",
        data_scope="train",
        search_space_hash="sha256:space",
        objective="rank_ic",
        random_seed=1,
        n_candidates_seen_so_far=1,
        status=status,  # type: ignore[arg-type]
        decision="research_only",
        reason_codes=[],
        metrics_summary={"rank_ic": 0.02},
        previous_entry_hash=None,
        entry_hash="",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(),
    )


def test_ledger_appends_hash_chained_records(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.sqlite")
    first = ledger.append(_entry("trial-1"))
    second = ledger.append(_entry("trial-2", status="reject"))

    records = ledger.query()

    assert len(records) == 2
    assert first.previous_entry_hash is None
    assert second.previous_entry_hash == first.entry_hash
    assert ledger.verify_hash_chain()
    assert records[1].status == "reject"


def test_failed_trial_is_recorded_before_return(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.sqlite")
    ledger.append(_entry("trial-failed", status="error"))

    records = ledger.query(candidate_id="candidate-trial-failed")

    assert len(records) == 1
    assert records[0].status == "error"


def test_ledger_rejects_mutation(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.sqlite")
    ledger.append(_entry("trial-1"))

    with pytest.raises(TrialLedgerMutationError):
        ledger.update("trial-1", decision="paper_candidate")
    with pytest.raises(TrialLedgerMutationError):
        ledger.delete("trial-1")
