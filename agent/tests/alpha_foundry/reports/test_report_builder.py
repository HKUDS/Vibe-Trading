from __future__ import annotations

import json

from src.alpha_foundry.reports.builder import build_alpha_genesis_report
from src.alpha_foundry.reports.render_markdown import render_markdown
from src.alpha_quality.decision.model import (
    AlphaQualityDecision,
    HardFailureCode,
    QualityDecision,
)
from src.alpha_quality.model import AlphaQualityScorecard, ExecutionMetrics


def _scorecard() -> AlphaQualityScorecard:
    return AlphaQualityScorecard(
        factor_id="candidate-1",
        formula="rank(close)",
        factor_definition_hash="sha256:factor",
        scope="final_quality_decision",
        horizons=[1, 5],
        execution=ExecutionMetrics(
            uses_execution_return=True,
            return_mean=0.01,
            turnover_mean=0.3,
            cost_bps_mean=3.0,
        ),
        data_snapshot_ref="sha256:snapshot",
        trial_ledger_ref="ledger:fixture",
    )


def _decision() -> AlphaQualityDecision:
    return AlphaQualityDecision(
        schema_version="alpha_quality_decision.v1",
        factor_id="candidate-1",
        decision=QualityDecision.RESEARCH_ONLY,
        hard_failures=[HardFailureCode.PIT_CONTRACT_MISSING],
        warnings=[],
        cap_reasons=[HardFailureCode.PIT_CONTRACT_MISSING],
        total_quality_score=0.42,
    )


def test_report_builder_preserves_exact_decision_codes_and_trial_count() -> None:
    report = build_alpha_genesis_report(
        report_id="report-1",
        scorecard=_scorecard(),
        decision=_decision(),
        trial_entries=[{"trial_id": "t1"}, {"trial_id": "t2"}],
        data_snapshot={
            "snapshot_hash": "sha256:snapshot",
            "pit_contract_present": False,
            "survivorship_bias": True,
        },
        novelty_metrics={"max_factor_rank_corr_to_existing": 0.2},
        synergy_metrics={"delta_ir": 0.1},
        source_config={"api_key": "sk-secret"},
    )

    payload = report.to_dict()

    assert payload["hard_failures"] == ["PIT_CONTRACT_MISSING"]
    assert payload["decision"] == "research_only"
    assert payload["trial_count"] == 2
    assert payload["data_snapshot_hash"] == "sha256:snapshot"
    assert "sk-secret" not in json.dumps(payload)


def test_markdown_report_states_research_only_limitations() -> None:
    report = build_alpha_genesis_report(
        report_id="report-1",
        scorecard=_scorecard(),
        decision=_decision(),
    )

    markdown = render_markdown(report)

    assert "not live trading advice" in markdown
    assert "not production-ready" in markdown
