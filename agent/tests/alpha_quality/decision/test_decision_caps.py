from __future__ import annotations

from src.alpha_quality.decision.model import (
    AlphaQualityDecisionContext,
    HardFailureCode,
    QualityDecision,
)
from src.alpha_quality.decision.runner import QualityDecisionRunner
from src.alpha_quality.model import AlphaQualityScorecard, ExecutionMetrics


def _scorecard(**kwargs: object) -> AlphaQualityScorecard:
    defaults = {
        "factor_id": "candidate",
        "formula": "rank(close)",
        "factor_definition_hash": "sha256:factor",
        "scope": "final_quality_decision",
        "horizons": [1],
        "execution": ExecutionMetrics(uses_execution_return=True, return_mean=0.01),
        "data_snapshot_ref": "snapshot:fixture",
        "trial_ledger_ref": "ledger:fixture",
    }
    defaults.update(kwargs)
    return AlphaQualityScorecard(**defaults)


def test_non_reproducible_caps_at_research_only() -> None:
    scorecard = _scorecard(data_snapshot_ref=None, trial_ledger_ref=None)

    result = QualityDecisionRunner().run(scorecard, AlphaQualityDecisionContext())

    assert result.decision == QualityDecision.RESEARCH_ONLY
    assert HardFailureCode.NON_REPRODUCIBLE in result.hard_failures


def test_missing_execution_return_caps_at_research_only() -> None:
    scorecard = _scorecard(execution=ExecutionMetrics(uses_execution_return=False))

    result = QualityDecisionRunner().run(scorecard, AlphaQualityDecisionContext())

    assert result.decision == QualityDecision.RESEARCH_ONLY
    assert HardFailureCode.EXECUTION_RETURN_MISSING in result.hard_failures


def test_negative_execution_alpha_rejects() -> None:
    scorecard = _scorecard(
        execution=ExecutionMetrics(
            uses_execution_return=True,
            return_mean=-0.01,
            turnover_mean=80.0,
            cost_bps_mean=120.0,
        )
    )

    result = QualityDecisionRunner().run(scorecard, AlphaQualityDecisionContext())

    assert result.decision == QualityDecision.REJECT
    assert HardFailureCode.COST_EXCEEDS_ALPHA in result.hard_failures
