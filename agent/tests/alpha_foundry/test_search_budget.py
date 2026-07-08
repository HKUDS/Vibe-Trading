from __future__ import annotations

from datetime import datetime, timezone

from src.alpha_foundry.search import AlphaFoundrySearch
from src.alpha_foundry.seed_bank import AlphaSeed, SeedBank
from src.research_ledger.trial_ledger import TrialLedger


def test_search_respects_candidate_and_trial_budget(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "trials.sqlite")
    search = AlphaFoundrySearch(
        seed_bank=SeedBank(
            [
                AlphaSeed(seed_id="seed_a", formula="rank(close)", source="fixture"),
                AlphaSeed(seed_id="seed_b", formula="rank(volume)", source="fixture"),
            ]
        ),
        ledger=ledger,
        max_candidates=3,
        trial_budget=2,
        now=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    result = search.generate()

    assert result.n_candidates_seen == 2
    assert len(result.candidates) == 2
    assert result.trial_budget_exhausted
    assert len(ledger.query()) == 2
    assert ledger.verify_hash_chain()
