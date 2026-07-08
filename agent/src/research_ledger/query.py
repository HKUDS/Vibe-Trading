from __future__ import annotations

from pathlib import Path

from src.research_ledger.trial_ledger import TrialLedger, TrialLedgerEntry


def query_trials(path: str | Path, *, candidate_id: str | None = None) -> list[TrialLedgerEntry]:
    return TrialLedger(path).query(candidate_id=candidate_id)
