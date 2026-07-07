from __future__ import annotations

from src.reliability.quant.scorecard import (
    HARD_FAILURE_CODES,
    ClaimSet,
    EvidenceSet,
    ScorecardInputs,
    build_scorecard,
)


def test_hard_failure_codes_include_phase5_contract() -> None:
    assert {
        "PIT_FUTURE_DATA",
        "QUANT_NO_COST_MODEL_TRADABLE_CLAIM",
        "QUANT_NO_BENCHMARK_ALPHA_CLAIM",
        "QUANT_NO_OOS_GENERALIZATION_CLAIM",
        "QUANT_HISTORICAL_UNIVERSE_MISSING",
        "QUANT_EXECUTION_TIMESTAMPS_MISSING",
        "QUANT_TRIAL_COUNT_MISSING_BEST_TRIAL",
        "QUANT_ASHARE_MARKET_RULES_MISSING",
        "POLICY_DENY_IGNORED",
        "QUANT_SCORECARD_LLM_OVERRIDE_ATTEMPT",
        "QUANT_HIGH_CROWDING_NO_STRESS_TEST",
        "QUANT_REGIME_NEGATIVE_IC_NO_ACTIVATION",
        "QUANT_IS_IC_NEAR_ZERO",
    } <= HARD_FAILURE_CODES


def test_historical_universe_missing_hard_failure() -> None:
    card = build_scorecard(
        ScorecardInputs(
            scorecard_id="sc_universe",
            evidence=EvidenceSet(historical_universe_present=False),
        )
    )

    assert any(
        issue.code == "QUANT_HISTORICAL_UNIVERSE_MISSING"
        for issue in card.hard_failures
    )


def test_ashare_market_rules_missing_blocks_tradable_claim() -> None:
    card = build_scorecard(
        ScorecardInputs(
            scorecard_id="sc_ashare",
            claims=ClaimSet(tradable=True),
            evidence=EvidenceSet(ashare_market_rules_present=False),
        )
    )

    assert any(
        issue.code == "QUANT_ASHARE_MARKET_RULES_MISSING"
        for issue in card.hard_failures
    )


def test_policy_deny_ignored_hard_failure() -> None:
    card = build_scorecard(
        ScorecardInputs(
            scorecard_id="sc_policy",
            evidence=EvidenceSet(policy_denies_ignored=True),
        )
    )

    assert any(issue.code == "POLICY_DENY_IGNORED" for issue in card.hard_failures)


def test_scorecard_llm_override_attempt_hard_failure() -> None:
    card = build_scorecard(
        ScorecardInputs(
            scorecard_id="sc_llm_override",
            evidence=EvidenceSet(llm_override_attempt=True),
        )
    )

    assert any(
        issue.code == "QUANT_SCORECARD_LLM_OVERRIDE_ATTEMPT"
        for issue in card.hard_failures
    )
