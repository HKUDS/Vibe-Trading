from __future__ import annotations

from src.alpha_foundry.candidate_pool import CandidateExpression, make_candidate
from src.alpha_foundry.seed_bank import AlphaSeed


class SeedMutator:
    def __init__(self, *, max_candidates_per_seed: int = 8) -> None:
        self.max_candidates_per_seed = max(1, max_candidates_per_seed)

    def mutate(self, seed: AlphaSeed) -> list[CandidateExpression]:
        templates = [
            (seed.formula, "identity"),
            (f"rank({seed.formula})", "rank_wrap"),
            (f"decay_linear({seed.formula}, 3)", "decay_3"),
            (f"delay({seed.formula}, 1)", "delay_1"),
            (f"zscore({seed.formula})", "zscore_wrap"),
        ]
        candidates: list[CandidateExpression] = []
        seen: set[str] = set()
        for formula, mutation in templates:
            if len(formula) > 512:
                continue
            candidate = make_candidate(seed.seed_id, formula, mutation=mutation)
            if candidate.formula_hash in seen:
                continue
            seen.add(candidate.formula_hash)
            candidates.append(candidate)
            if len(candidates) >= self.max_candidates_per_seed:
                break
        return candidates
