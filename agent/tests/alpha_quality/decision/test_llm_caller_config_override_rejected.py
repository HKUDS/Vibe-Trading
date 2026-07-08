from __future__ import annotations

from src.alpha_quality.decision.model import AlphaQualityDecisionContext, HardFailureCode, QualityDecision
from src.alpha_quality.decision.runner import QualityDecisionRunner
from src.alpha_quality.model import AlphaQualityScorecard, ExecutionMetrics


def _scorecard() -> AlphaQualityScorecard:
    return AlphaQualityScorecard(
        factor_id="candidate",
        formula="rank(close)",
        factor_definition_hash="sha256:factor",
        scope="final_quality_decision",
        horizons=[1],
        execution=ExecutionMetrics(uses_execution_return=True, return_mean=0.01),
        data_snapshot_ref="sha256:snapshot",
        trial_ledger_ref="ledger:fixture",
    )


def test_llm_or_caller_cannot_raise_quality_decision_above_deterministic_result() -> None:
    result = QualityDecisionRunner().run(
        _scorecard(),
        AlphaQualityDecisionContext(
            caller_claimed_decision=QualityDecision.FORWARD_TRACK,
            total_quality_score=0.10,
        ),
    )

    assert result.decision == QualityDecision.REJECT
    assert HardFailureCode.SCORECARD_OVERRIDE_ATTEMPT in result.hard_failures


def test_caller_claim_matching_or_lower_result_is_not_an_override_attempt() -> None:
    result = QualityDecisionRunner().run(
        _scorecard(),
        AlphaQualityDecisionContext(
            caller_claimed_decision=QualityDecision.RESEARCH_ONLY,
            total_quality_score=0.10,
        ),
    )

    assert result.decision == QualityDecision.RESEARCH_ONLY
    assert HardFailureCode.SCORECARD_OVERRIDE_ATTEMPT not in result.hard_failures
