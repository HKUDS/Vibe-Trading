from __future__ import annotations

import json
from datetime import datetime, timezone

from src.research_ledger.hash_utils import redact_secrets
from src.research_ledger.trial_ledger import TrialLedger, TrialLedgerEntry


def test_redact_secrets_recurses_through_source_config() -> None:
    redacted = redact_secrets(
        {
            "provider": "fixture",
            "token": "sk-secret",
            "nested": {"api_key": "abc123", "safe": "kept"},
        }
    )

    payload = json.dumps(redacted)

    assert "sk-secret" not in payload
    assert "abc123" not in payload
    assert redacted["nested"]["safe"] == "kept"


def test_ledger_redacts_sensitive_parameter_variants(tmp_path) -> None:
    entry = TrialLedgerEntry(
        trial_id="trial-secret",
        trial_group_id="group",
        parent_trial_id=None,
        candidate_id="candidate-secret",
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
        status="success",
        decision="research_only",
        reason_codes=[],
        parameter_variant={"api_key": "sk-secret", "window": 20},
        metrics_summary={"token": "also-secret", "rank_ic": 0.01},
        previous_entry_hash=None,
        entry_hash="",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(),
    )
    ledger = TrialLedger(tmp_path / "ledger.sqlite")

    stored = ledger.append(entry)
    payload = json.dumps(stored.to_dict())

    assert "sk-secret" not in payload
    assert "also-secret" not in payload
    assert stored.parameter_variant["window"] == 20
