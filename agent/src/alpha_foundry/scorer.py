from __future__ import annotations


def score_candidate_quality(
    *,
    predictive_score: float,
    robustness_score: float,
    tradability_score: float,
    novelty_score: float,
    marginal_portfolio_score: float,
    data_quality_score: float,
    complexity_penalty: float,
    crowding_penalty: float,
    test_leakage_penalty: float,
) -> float:
    raw_score = (
        0.25 * predictive_score
        + 0.20 * robustness_score
        + 0.18 * tradability_score
        + 0.15 * novelty_score
        + 0.17 * marginal_portfolio_score
        + 0.05 * data_quality_score
        - complexity_penalty
        - crowding_penalty
        - test_leakage_penalty
    )
    return max(0.0, min(1.0, float(raw_score)))
