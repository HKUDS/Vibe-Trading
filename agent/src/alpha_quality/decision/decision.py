from __future__ import annotations

from src.alpha_quality.decision.model import HardFailureCode, QualityDecision


REJECT_FAILURES = {
    HardFailureCode.LOOKAHEAD_DETECTED,
    HardFailureCode.TEST_SET_CONTAMINATED,
    HardFailureCode.COST_EXCEEDS_ALPHA,
    HardFailureCode.DUPLICATE_ALPHA,
    HardFailureCode.SCORECARD_OVERRIDE_ATTEMPT,
}

RESEARCH_ONLY_CAPS = {
    HardFailureCode.NON_REPRODUCIBLE,
    HardFailureCode.PIT_CONTRACT_MISSING,
    HardFailureCode.EXECUTION_RETURN_MISSING,
}

DECISION_RANK = {
    QualityDecision.REJECT: 0,
    QualityDecision.RESEARCH_ONLY: 1,
    QualityDecision.CANDIDATE_ZOO: 2,
    QualityDecision.PAPER_CANDIDATE: 3,
    QualityDecision.FORWARD_TRACK: 4,
}


def decide_quality(
    hard_failures: set[HardFailureCode],
    *,
    total_quality_score: float,
) -> QualityDecision:
    if hard_failures & REJECT_FAILURES:
        return QualityDecision.REJECT
    if hard_failures & RESEARCH_ONLY_CAPS:
        return QualityDecision.RESEARCH_ONLY
    if total_quality_score >= 0.90:
        return QualityDecision.FORWARD_TRACK
    if total_quality_score >= 0.75:
        return QualityDecision.PAPER_CANDIDATE
    if total_quality_score >= 0.50:
        return QualityDecision.CANDIDATE_ZOO
    return QualityDecision.RESEARCH_ONLY


def is_decision_raise(
    claimed: QualityDecision,
    actual: QualityDecision,
) -> bool:
    return DECISION_RANK[claimed] > DECISION_RANK[actual]


def cap_reasons(hard_failures: set[HardFailureCode]) -> list[HardFailureCode]:
    return sorted(hard_failures & RESEARCH_ONLY_CAPS, key=lambda code: code.value)
