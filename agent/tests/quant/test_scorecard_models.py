from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.reliability.quant.scorecard import (
    SCORECARD_DIMENSION_KEYS,
    BacktestReliabilityScorecard,
    QuantIssue,
)


def test_score_breakdown_key_whitelist() -> None:
    assert SCORECARD_DIMENSION_KEYS == {
        "pit_clean",
        "oos_split",
        "cost_model",
        "benchmark",
        "trial_count",
        "execution_realism",
        "universe_pit",
        "capacity",
        "cost_sensitivity",
        "ic_stability",
        "regime_stability",
        "crowding_risk",
        "random_control",
    }

    card = BacktestReliabilityScorecard.minimal(scorecard_id="sc_test")

    assert card.schema_version == "1.0.0"
    assert set(card.score_breakdown) == SCORECARD_DIMENSION_KEYS
    assert all(value == 0.0 for value in card.score_breakdown.values())


def test_score_breakdown_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        BacktestReliabilityScorecard(
            scorecard_id="sc_bad",
            schema_version="1.0.0",
            score=0.0,
            score_breakdown={"oos": 1.0},
            conclusion_cap="exploratory",
        )


def test_missing_dimension_explicit_zero_or_warning() -> None:
    card = BacktestReliabilityScorecard(
        scorecard_id="sc_partial",
        schema_version="1.0.0",
        score=0.0,
        score_breakdown={"pit_clean": 1.0},
        conclusion_cap="exploratory",
        warnings=[
            QuantIssue(
                code="QUANT_SCORECARD_DIMENSION_DEFAULTED",
                severity="warning",
                message="missing dimensions defaulted to zero",
            )
        ],
    )

    assert set(card.score_breakdown) == SCORECARD_DIMENSION_KEYS
    assert card.score_breakdown["pit_clean"] == 1.0
    assert card.score_breakdown["oos_split"] == 0.0
    assert any(issue.code == "QUANT_SCORECARD_DIMENSION_DEFAULTED" for issue in card.warnings)


def test_warnings_and_hard_failures_are_structured() -> None:
    card = BacktestReliabilityScorecard.minimal(
        scorecard_id="sc_structured",
        warnings=[
            QuantIssue(
                code="QUANT_TEST_WARNING",
                severity="warning",
                message="test warning",
                metadata={"dimension": "cost_model"},
            )
        ],
        hard_failures=[
            QuantIssue(
                code="QUANT_NO_COST_MODEL_TRADABLE_CLAIM",
                severity="hard_failure",
                message="tradability claim requires a cost model",
            )
        ],
    )

    dumped = card.model_dump(mode="json")

    assert dumped["warnings"][0]["code"] == "QUANT_TEST_WARNING"
    assert dumped["hard_failures"][0]["severity"] == "hard_failure"
