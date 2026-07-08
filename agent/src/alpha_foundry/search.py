from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from src.alpha_foundry.candidate_pool import CandidateExpression
from src.alpha_foundry.mutators import SeedMutator
from src.alpha_foundry.seed_bank import SeedBank
from src.research_ledger.hash_utils import canonical_json_hash
from src.research_ledger.trial_ledger import TrialLedger, TrialLedgerEntry


@dataclass(frozen=True)
class AlphaFoundrySearchResult:
    candidates: list[CandidateExpression]
    n_candidates_seen: int
    trial_budget_exhausted: bool


class AlphaFoundrySearch:
    def __init__(
        self,
        *,
        seed_bank: SeedBank,
        ledger: TrialLedger | None = None,
        mutator: SeedMutator | None = None,
        max_candidates: int = 2000,
        trial_budget: int = 5000,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.seed_bank = seed_bank
        self.ledger = ledger
        self.mutator = mutator or SeedMutator()
        self.max_candidates = max(0, max_candidates)
        self.trial_budget = max(0, trial_budget)
        self.now = now or (lambda: datetime.now(timezone.utc))

    def generate(self) -> AlphaFoundrySearchResult:
        candidates: list[CandidateExpression] = []
        seen = 0
        for seed in self.seed_bank.list():
            for candidate in self.mutator.mutate(seed):
                if seen >= self.max_candidates or seen >= self.trial_budget:
                    return AlphaFoundrySearchResult(
                        candidates=candidates,
                        n_candidates_seen=seen,
                        trial_budget_exhausted=seen >= self.trial_budget,
                    )
                seen += 1
                candidates.append(candidate)
                if self.ledger is not None:
                    self.ledger.append(self._trial_record(candidate, seen))
        return AlphaFoundrySearchResult(
            candidates=candidates,
            n_candidates_seen=seen,
            trial_budget_exhausted=seen >= self.trial_budget,
        )

    def _trial_record(
        self, candidate: CandidateExpression, count: int
    ) -> TrialLedgerEntry:
        created = self.now().astimezone(timezone.utc).isoformat()
        return TrialLedgerEntry(
            trial_id=f"trial-{candidate.candidate_id}-{count}",
            trial_group_id="alpha_foundry_search",
            parent_trial_id=None,
            candidate_id=candidate.candidate_id,
            parent_seed_id=candidate.parent_seed_id,
            formula=candidate.formula,
            formula_hash=candidate.formula_hash,
            data_snapshot_hash="sha256:unavailable",
            universe_hash="sha256:unavailable",
            split_id="train",
            data_scope="train",
            search_space_hash=canonical_json_hash(
                {"max_candidates": self.max_candidates, "trial_budget": self.trial_budget}
            ),
            objective="candidate_generation",
            random_seed=None,
            n_candidates_seen_so_far=count,
            status="success",
            decision="none",
            reason_codes=[],
            parameter_variant=candidate.metadata,
            metrics_summary={},
            previous_entry_hash=None,
            entry_hash="",
            created_at=created,
        )
