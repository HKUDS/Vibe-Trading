from __future__ import annotations

from src.reliability.quant.scorecard import (
    ClaimSet,
    EvidenceSet,
    ExecutionTimestampSet,
    ScorecardInputs,
    build_scorecard,
    should_generate_scorecard,
)


def _build(evidence: EvidenceSet, claims: ClaimSet | None = None):
    return build_scorecard(
        ScorecardInputs(
            scorecard_id="sc_gate",
            claims=claims or ClaimSet(),
            evidence=evidence,
        )
    )


def test_no_cost_model_caps_conclusion() -> None:
    card = _build(EvidenceSet(cost_model_present=False))

    assert card.conclusion_cap != "paper_trade_candidate"
    assert card.score_breakdown["cost_model"] == 0.0
    assert any(issue.code == "QUANT_COST_MODEL_MISSING" for issue in card.warnings)


def test_no_cost_model_tradable_claim_is_hard_failure() -> None:
    card = _build(
        EvidenceSet(cost_model_present=False),
        ClaimSet(tradable=True),
    )

    assert card.conclusion_cap == "not_reliable"
    assert any(
        issue.code == "QUANT_NO_COST_MODEL_TRADABLE_CLAIM"
        for issue in card.hard_failures
    )


def test_no_oos_caps_conclusion() -> None:
    card = _build(EvidenceSet(oos_present=False))

    assert card.conclusion_cap != "paper_trade_candidate"
    assert card.score_breakdown["oos_split"] == 0.0
    assert any(issue.code == "QUANT_OOS_MISSING" for issue in card.warnings)


def test_no_oos_generalization_claim_is_hard_failure() -> None:
    card = _build(EvidenceSet(oos_present=False), ClaimSet(generalization=True))

    assert card.conclusion_cap == "not_reliable"
    assert any(
        issue.code == "QUANT_NO_OOS_GENERALIZATION_CLAIM"
        for issue in card.hard_failures
    )


def test_no_benchmark_prevents_alpha_claim() -> None:
    card = _build(EvidenceSet(benchmark_present=False), ClaimSet(alpha=True))

    assert card.conclusion_cap == "not_reliable"
    assert card.score_breakdown["benchmark"] == 0.0
    assert any(
        issue.code == "QUANT_NO_BENCHMARK_ALPHA_CLAIM"
        for issue in card.hard_failures
    )


def test_missing_trial_count_prevents_best_trial_claim() -> None:
    card = _build(EvidenceSet(trial_count=None), ClaimSet(best_trial=True))

    assert card.conclusion_cap == "not_reliable"
    assert any(
        issue.code == "QUANT_TRIAL_COUNT_MISSING_BEST_TRIAL"
        for issue in card.hard_failures
    )


def test_execution_timestamp_missing_prevents_tradable_claim() -> None:
    card = _build(
        EvidenceSet(
            execution_timestamps=ExecutionTimestampSet(
                signal_time=True,
                decision_time=True,
                order_time=False,
                fill_time=True,
                price_time=True,
            )
        ),
        ClaimSet(tradable=True),
    )

    assert card.conclusion_cap == "not_reliable"
    assert card.score_breakdown["execution_realism"] == 0.0
    assert any(
        issue.code == "QUANT_EXECUTION_TIMESTAMPS_MISSING"
        for issue in card.hard_failures
    )


def test_pit_violation_hard_failure() -> None:
    card = _build(EvidenceSet(pit_violation_codes=["PIT_FUTURE_DATA"]))

    assert card.conclusion_cap == "not_reliable"
    assert card.score_breakdown["pit_clean"] == 0.0
    assert any(issue.code == "PIT_FUTURE_DATA" for issue in card.hard_failures)


def test_reliability_mode_off_skips_scorecard(monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "off")

    assert should_generate_scorecard() is False
