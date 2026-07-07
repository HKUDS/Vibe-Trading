"""Tests for Phase 4 scorecard policy gates over claims and facts."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.reliability.artifacts.store import ArtifactStore
from src.reliability.claims.extractor import build_claim_set_from_research_card
from src.reliability.quant.methodology_facts import MethodologyFactSet
from src.reliability.quant.scorecard import BacktestReliabilityScorecard
from src.reliability.quant.scorecard_policy import PredicateInput, ScorecardPolicyEngine


def test_tradable_claim_without_cost_model_hard_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    result = _evaluate(
        tmp_path,
        claim_type="tradable",
        facts=MethodologyFactSet(run_id="run_tradable", has_cost_model=False),
    )

    assert "tradable_claim_without_cost_model" in result.scorecard.hard_failures
    assert result.scorecard.conclusion_level == "not_reliable"
    assert result.scorecard.triggered_rules[0].rule_id == "tradable_claim_without_cost_model"
    assert result.scorecard.triggered_rules[0].evidence_refs


def test_alpha_claim_without_benchmark_hard_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    result = _evaluate(
        tmp_path,
        claim_type="alpha",
        facts=MethodologyFactSet(run_id="run_alpha", has_benchmark=False),
    )

    assert "alpha_claim_without_benchmark" in result.scorecard.hard_failures
    assert result.scorecard.conclusion_level == "not_reliable"


def test_generalization_claim_without_oos_caps_research_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    result = _evaluate(
        tmp_path,
        claim_type="generalization",
        facts=MethodologyFactSet(run_id="run_gen", has_oos=False),
        conclusion_level="paper_trade_candidate",
    )

    assert result.scorecard.hard_failures == []
    assert result.scorecard.conclusion_level == "research_candidate"
    assert [rule.rule_id for rule in result.scorecard.triggered_rules] == [
        "generalization_claim_without_oos"
    ]


def test_paper_gate_requires_all_methodology_facts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    result = _evaluate(
        tmp_path,
        claim_type="paper_trade_candidate",
        facts=MethodologyFactSet(
            run_id="run_paper",
            has_cost_model=True,
            has_benchmark=True,
            has_oos=False,
            has_execution_timeline=False,
            has_capacity_test=False,
            has_market_rule_coverage=False,
        ),
        conclusion_level="paper_trade_candidate",
    )

    assert "paper_gate_without_all_requirements" in result.scorecard.hard_failures
    assert result.scorecard.conclusion_level == "not_reliable"
    assert "has_oos" in result.scorecard.triggered_rules[0].explanation


def test_high_returns_do_not_override_pit_hard_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    result = _evaluate(
        tmp_path,
        claim_type="alpha",
        facts=MethodologyFactSet(run_id="run_pit", pit_safe=False, has_benchmark=True),
        scorecard=BacktestReliabilityScorecard(
            run_id="run_pit",
            conclusion_level="paper_trade_candidate",
            metrics={"sharpe": 9.8, "annual_return": 7.2},
        ),
    )

    assert "pit_violation_hard_fail" in result.scorecard.hard_failures
    assert result.scorecard.conclusion_level == "not_reliable"


def _evaluate(
    tmp_path: Path,
    *,
    claim_type: str,
    facts: MethodologyFactSet,
    conclusion_level: str = "research_candidate",
    scorecard: BacktestReliabilityScorecard | None = None,
) -> object:
    run_id = facts.run_id
    claim_set = build_claim_set_from_research_card(
        {
            "run_id": run_id,
            "structured_claims": [
                {
                    "claim_type": claim_type,
                    "claim_text": f"{claim_type} claim for {run_id}",
                    "source_ref": "research_card.structured_claims[0]",
                    "evidence_refs": [f"art_{claim_type}"],
                }
            ],
        }
    )
    scorecard = scorecard or BacktestReliabilityScorecard(
        run_id=run_id,
        conclusion_level=conclusion_level,
    )
    return ScorecardPolicyEngine.default().evaluate(
        PredicateInput(
            scorecard=scorecard,
            claim_set=claim_set,
            methodology_facts=facts,
            artifact_store=ArtifactStore(tmp_path / "artifacts"),
        )
    )
