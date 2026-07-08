from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.research_ledger.hash_utils import canonical_json_hash


@dataclass(frozen=True)
class CandidateExpression:
    candidate_id: str
    parent_seed_id: str
    formula: str
    formula_hash: str
    metadata: dict[str, Any]


def make_candidate(parent_seed_id: str, formula: str, *, mutation: str) -> CandidateExpression:
    formula_hash = canonical_json_hash({"formula": formula})
    return CandidateExpression(
        candidate_id=formula_hash.removeprefix("sha256:")[:16],
        parent_seed_id=parent_seed_id,
        formula=formula,
        formula_hash=formula_hash,
        metadata={"mutation": mutation},
    )
