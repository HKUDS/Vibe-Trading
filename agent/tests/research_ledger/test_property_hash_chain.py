from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.research_ledger.trial_ledger import TrialLedger, TrialLedgerEntry


TrialStatus = Literal["success", "reject", "skip", "error"]


def _entry(trial_id: str, status: TrialStatus, index: int) -> TrialLedgerEntry:
    return TrialLedgerEntry(
        trial_id=trial_id,
        trial_group_id="property-group",
        parent_trial_id=None,
        candidate_id=f"candidate-{index}",
        parent_seed_id=None,
        formula="rank(close)",
        formula_hash=f"sha256:formula-{index}",
        data_snapshot_hash="sha256:snapshot",
        universe_hash="sha256:universe",
        split_id="train-valid",
        data_scope="train",
        search_space_hash="sha256:space",
        objective="rank_ic",
        random_seed=index,
        n_candidates_seen_so_far=index + 1,
        status=status,
        decision="research_only" if status == "success" else "reject",
        reason_codes=[] if status == "success" else [f"{status.upper()}_FIXTURE"],
        metrics_summary={"rank_ic": 0.01 * index, "status_recorded": status},
        previous_entry_hash=None,
        entry_hash="",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(),
    )


@given(
    statuses=st.lists(
        st.sampled_from(["success", "reject", "skip", "error"]),
        min_size=1,
        max_size=24,
    )
)
@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_trial_ledger_hash_chain_property_records_all_statuses(
    tmp_path, statuses: list[TrialStatus]
) -> None:
    ledger = TrialLedger(tmp_path / f"property-ledger-{uuid4().hex}.sqlite")

    for index, status in enumerate(statuses):
        ledger.append(_entry(f"trial-{index}", status, index))

    records = ledger.query()

    assert [record.status for record in records] == statuses
    assert ledger.verify_hash_chain()
    assert records[0].previous_entry_hash is None
    for previous, current in zip(records, records[1:]):
        assert current.previous_entry_hash == previous.entry_hash
