from __future__ import annotations

from src.alpha_foundry.mutators import SeedMutator
from src.alpha_foundry.seed_bank import AlphaSeed


def test_mutator_generates_bounded_candidates_with_hashes() -> None:
    seed = AlphaSeed(seed_id="seed_reversal", formula="rank(neg(ret_1d))", source="fixture")

    candidates = SeedMutator(max_candidates_per_seed=4).mutate(seed)

    assert 1 <= len(candidates) <= 4
    assert all(candidate.parent_seed_id == "seed_reversal" for candidate in candidates)
    assert all(candidate.formula_hash.startswith("sha256:") for candidate in candidates)
    assert len({candidate.formula_hash for candidate in candidates}) == len(candidates)


def test_mutator_keeps_candidate_formulas_within_length_limit() -> None:
    seed = AlphaSeed(seed_id="seed", formula="rank(close)", source="fixture")

    candidates = SeedMutator(max_candidates_per_seed=10).mutate(seed)

    assert all(len(candidate.formula) <= 512 for candidate in candidates)
