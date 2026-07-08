from __future__ import annotations

from src.alpha_quality.decision.model import AlphaQualityDecisionContext, HardFailureCode, QualityDecision
from src.alpha_quality.decision.runner import QualityDecisionRunner
from src.alpha_quality.model import AlphaQualityScorecard, ExecutionMetrics


def _scorecard(**kwargs: object) -> AlphaQualityScorecard:
    defaults = {
        "factor_id": "candidate",
        "formula": "rank(close)",
        "factor_definition_hash": "sha256:factor",
        "scope": "final_quality_decision",
        "horizons": [1],
        "execution": ExecutionMetrics(uses_execution_return=True, return_mean=0.02),
        "data_snapshot_ref": "sha256:snapshot",
        "trial_ledger_ref": "ledger:fixture",
    }
    defaults.update(kwargs)
    return AlphaQualityScorecard(**defaults)


def test_high_score_can_forward_track_only_when_no_caps_or_hard_failures() -> None:
    result = QualityDecisionRunner().run(
        _scorecard(),
        AlphaQualityDecisionContext(total_quality_score=0.95),
    )

    assert result.decision == QualityDecision.FORWARD_TRACK
    assert result.hard_failures == []


def test_pit_missing_caps_even_high_score_at_research_only() -> None:
    result = QualityDecisionRunner().run(
        _scorecard(),
        AlphaQualityDecisionContext(total_quality_score=0.95, pit_contract_present=False),
    )

    assert result.decision == QualityDecision.RESEARCH_ONLY
    assert result.cap_reasons == [HardFailureCode.PIT_CONTRACT_MISSING]


def test_missing_ledger_or_snapshot_caps_at_research_only() -> None:
    result = QualityDecisionRunner().run(
        _scorecard(data_snapshot_ref=None, trial_ledger_ref=None),
        AlphaQualityDecisionContext(total_quality_score=0.95),
    )

    assert result.decision == QualityDecision.RESEARCH_ONLY
    assert HardFailureCode.NON_REPRODUCIBLE in result.cap_reasons


def test_duplicate_alpha_rejects_unless_used_as_explicit_baseline_control() -> None:
    result = QualityDecisionRunner().run(
        _scorecard(),
        AlphaQualityDecisionContext(total_quality_score=0.95, duplicate_alpha=True),
    )

    assert result.decision == QualityDecision.REJECT
    assert HardFailureCode.DUPLICATE_ALPHA in result.hard_failures
