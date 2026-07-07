"""Phase 9 diagnostics readiness bridge tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.reliability.artifacts.store import ArtifactStore
from src.reliability.claims.model import ClaimSet
from src.reliability.quant.diagnostics import (
    CapacityDiagnosticsSummary,
    DiagnosticsReadinessReport,
    ExecutionDiagnosticsSummary,
    FactorDiagnosticsSummary,
    PortfolioDiagnosticsSummary,
)
from src.reliability.quant.methodology_facts import MethodologyFactSet
from src.reliability.quant.scorecard import BacktestReliabilityScorecard
from src.reliability.quant.scorecard_policy import PredicateInput, ScorecardPolicyEngine
from src.research_card.model import ResearchCard
from src.research_card.render_markdown import render_research_card_markdown


def test_old_scorecard_loads_without_diagnostics() -> None:
    scorecard = BacktestReliabilityScorecard.model_validate(
        {
            "schema_version": "1.2",
            "run_id": "legacy_scorecard",
            "conclusion_level": "research_candidate",
        }
    )

    assert scorecard.factor_diagnostics is None
    assert scorecard.portfolio_diagnostics is None
    assert scorecard.execution_diagnostics is None
    assert scorecard.capacity_diagnostics is None
    assert scorecard.diagnostics_readiness is None


def test_diagnostics_round_trip_json() -> None:
    report = DiagnosticsReadinessReport(
        run_id="run_diag",
        factor=FactorDiagnosticsSummary(
            data_audit_available=True,
            pit_safe=True,
            benchmark_available=True,
            oos_available=False,
            trial_count=12,
            readiness_gaps=["factor_oos_missing"],
        ),
        portfolio=PortfolioDiagnosticsSummary(
            cost_model_available=True,
            market_rule_coverage_available=False,
            readiness_gaps=["portfolio_market_rules_missing"],
        ),
        execution=ExecutionDiagnosticsSummary(
            execution_timeline_available=True,
            timestamps_present=["signal_time", "order_time"],
        ),
        capacity=CapacityDiagnosticsSummary(
            capacity_test_available=True,
            adv_caps_tested=[0.01, 0.05],
        ),
        readiness_gaps=["factor_oos_missing", "portfolio_market_rules_missing"],
    )

    loaded = DiagnosticsReadinessReport.model_validate_json(report.model_dump_json())

    assert loaded.schema_version == "1.2.1"
    assert loaded.factor is not None
    assert loaded.factor.trial_count == 12
    assert loaded.execution is not None
    assert loaded.execution.timestamps_present == ["signal_time", "order_time"]
    assert loaded.readiness_gaps == ["factor_oos_missing", "portfolio_market_rules_missing"]


def test_diagnostics_render_markdown_optional_section() -> None:
    readiness = DiagnosticsReadinessReport(
        run_id="run_markdown_diag",
        execution=ExecutionDiagnosticsSummary(
            execution_timeline_available=False,
            readiness_gaps=["execution_timeline_missing"],
        ),
        readiness_gaps=["execution_timeline_missing"],
    )
    scorecard = BacktestReliabilityScorecard(
        run_id="run_markdown_diag",
        diagnostics_readiness=readiness,
    )

    markdown = render_research_card_markdown(
        ResearchCard(run_id="run_markdown_diag", conclusion_level="exploratory"),
        scorecard=scorecard,
    )

    assert "## Diagnostics Availability" in markdown
    assert "execution_timeline_missing" in markdown
    assert "readiness only; not production diagnostics" in markdown


def test_missing_diagnostics_do_not_change_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    scorecard = BacktestReliabilityScorecard(
        run_id="run_missing_diagnostics",
        conclusion_level="paper_trade_candidate",
        diagnostics_readiness=DiagnosticsReadinessReport(
            run_id="run_missing_diagnostics",
            readiness_gaps=["execution_timeline_missing", "capacity_test_missing"],
        ),
    )

    result = ScorecardPolicyEngine.default().evaluate(
        PredicateInput(
            scorecard=scorecard,
            claim_set=ClaimSet(
                claim_set_id="claims_missing_diagnostics",
                run_id="run_missing_diagnostics",
                extractor_version="test",
                generated_by="phase9",
            ),
            methodology_facts=MethodologyFactSet(run_id="run_missing_diagnostics"),
            artifact_store=ArtifactStore(tmp_path / "artifacts"),
        )
    )

    assert result.scorecard.conclusion_level == "paper_trade_candidate"
    assert result.scorecard.hard_failures == []
    assert result.scorecard.diagnostics_readiness is not None
    assert result.scorecard.diagnostics_readiness.readiness_gaps == [
        "execution_timeline_missing",
        "capacity_test_missing",
    ]


def test_methodology_facts_feed_diagnostics_readiness() -> None:
    facts = MethodologyFactSet(
        run_id="run_fact_diag",
        trial_count=8,
        has_data_audit=True,
        pit_safe=True,
        has_cost_model=True,
        has_benchmark=True,
        has_oos=True,
        has_execution_timeline=False,
        has_capacity_test=True,
        adv_caps_tested=[0.01, 0.05],
        has_market_rule_coverage=False,
        generated_from_artifacts=["art_methodology_facts"],
    )

    report = facts.to_diagnostics_readiness_report()

    assert report.run_id == "run_fact_diag"
    assert report.factor is not None
    assert report.factor.data_audit_available is True
    assert report.factor.pit_safe is True
    assert report.factor.benchmark_available is True
    assert report.factor.oos_available is True
    assert report.factor.trial_count == 8
    assert report.execution is not None
    assert report.execution.execution_timeline_available is False
    assert report.capacity is not None
    assert report.capacity.capacity_test_available is True
    assert report.capacity.adv_caps_tested == [0.01, 0.05]
    assert "execution_timeline_missing" in report.readiness_gaps
    assert "portfolio_market_rules_missing" in report.readiness_gaps
    assert report.generated_from_artifacts == ["art_methodology_facts"]
