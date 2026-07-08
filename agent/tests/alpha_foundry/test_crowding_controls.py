from __future__ import annotations

from src.alpha_foundry.scorer import score_candidate_quality


def test_crowding_penalty_caps_duplicate_candidate_score() -> None:
    score = score_candidate_quality(
        predictive_score=0.9,
        robustness_score=0.8,
        tradability_score=0.8,
        novelty_score=0.0,
        marginal_portfolio_score=-0.1,
        data_quality_score=0.7,
        complexity_penalty=0.0,
        crowding_penalty=0.5,
        test_leakage_penalty=0.0,
    )

    assert score < 0.5
