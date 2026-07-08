from __future__ import annotations

from src.alpha_quality.decision.model import (
    AdvisoryCode,
    AlphaQualityDecision,
    HardFailureCode,
    QualityDecision,
)


def test_quality_decision_return_values_are_exact_research_labels() -> None:
    allowed = {
        "reject",
        "research_only",
        "candidate_zoo",
        "paper_candidate",
        "forward_track",
    }

    assert {item.value for item in QualityDecision} == allowed
    assert "live_ready" not in allowed
    assert "production_ready" not in allowed


def test_quality_decision_json_schema_has_no_caller_controlled_extra_claims() -> None:
    decision = AlphaQualityDecision(
        schema_version="alpha_quality_decision.v1",
        factor_id="candidate",
        decision=QualityDecision.RESEARCH_ONLY,
        hard_failures=[HardFailureCode.PIT_CONTRACT_MISSING],
        warnings=[AdvisoryCode.HIGH_PBO_PROXY, AdvisoryCode.LOW_DEFLATED_SHARPE],
        cap_reasons=[HardFailureCode.PIT_CONTRACT_MISSING],
        total_quality_score=0.1,
    )

    payload = decision.to_dict()

    assert set(payload) == {
        "schema_version",
        "factor_id",
        "decision",
        "hard_failures",
        "warnings",
        "cap_reasons",
        "total_quality_score",
    }
    assert payload["hard_failures"] == ["PIT_CONTRACT_MISSING"]
    assert payload["warnings"] == ["HIGH_PBO_PROXY", "LOW_DEFLATED_SHARPE"]
