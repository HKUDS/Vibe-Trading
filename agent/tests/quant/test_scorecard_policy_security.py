"""Security tests for Phase 4 scorecard policy loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.reliability.quant.scorecard import BacktestReliabilityScorecard
from src.reliability.quant.scorecard_policy import ScorecardPolicyEngine


def test_malicious_yaml_cannot_execute_code(tmp_path: Path) -> None:
    marker = tmp_path / "executed.txt"
    policy_path = tmp_path / "malicious.yaml"
    policy_path.write_text(
        f"!!python/object/apply:os.system ['echo owned > {marker}']\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid scorecard policy YAML"):
        ScorecardPolicyEngine.from_yaml(policy_path)

    assert not marker.exists()


def test_policy_override_cannot_weaken_builtin_hard_gate(tmp_path: Path) -> None:
    policy_path = tmp_path / "weaken.yaml"
    policy_path.write_text(
        """
rules:
  - rule_id: tradable_claim_without_cost_model
    predicate_name: tradable_claim_without_cost_model
    action: hard_fail
    reason_code: TRADABLE_WITHOUT_COST
    explanation_template: blocked
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing built-in rules"):
        ScorecardPolicyEngine.from_yaml(policy_path)


def test_old_scorecard_without_triggered_rules_loads() -> None:
    scorecard = BacktestReliabilityScorecard.model_validate(
        {
            "schema_version": "1.2.0",
            "run_id": "run_old_scorecard",
            "conclusion_level": "research_candidate",
            "hard_failures": [],
        }
    )

    assert scorecard.triggered_rules == []
    assert scorecard.policy_rule_version is None
    assert scorecard.claim_set_ref is None
    assert scorecard.methodology_fact_ref is None
