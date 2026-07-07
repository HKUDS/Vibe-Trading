from __future__ import annotations

from datetime import datetime, timezone

from src.governance.decisions import PolicyDecision
from src.reliability.data.contracts import DataAccessContract, DataAuditReport, StructuredWarning
from src.reliability.quant.scorecard import (
    BacktestReliabilityScorecard,
    QuantIssue,
    SCORECARD_DIMENSION_KEYS,
)
from src.research_card.builder import ResearchCardGraph, build_research_card
from src.research_protocol.model import (
    BenchmarkSpec,
    CostModelSpec,
    DataSetContract,
    EvaluationPlan,
    ResearchProtocol,
    SplitSpec,
    UniverseSpec,
)


def _protocol() -> ResearchProtocol:
    return ResearchProtocol(
        protocol_id="proto_1",
        protocol_hash="proto_hash",
        schema_version="1.0.0",
        status="registered",
        hypothesis="Large-cap reversal persists after costs.",
        universe=UniverseSpec(asset_class="us_equity", symbols=["SPY"], point_in_time=True),
        data_requirements=[
            DataSetContract(
                dataset_id="ohlcv",
                asset_class="us_equity",
                frequency="1D",
                calendar="NYSE",
                fields=["open", "close", "volume"],
                timezone="UTC",
            )
        ],
        split_policy=SplitSpec(method="walk_forward", fold_count=3),
        benchmark_policy=BenchmarkSpec(primary="SPY"),
        cost_model=CostModelSpec(commission_bps=1.0, slippage_bps=5.0),
        evaluation_plan=EvaluationPlan(metrics=["sharpe"], oos_required=True),
        created_at=datetime.now(timezone.utc),
        created_by="test",
    )


def _data_audit() -> DataAuditReport:
    return DataAuditReport(
        audit_id="audit_1",
        schema_version="1.0.0",
        access_contract=DataAccessContract(
            source="auto",
            selected_source="local_cache",
            request_params_hash="a" * 64,
            fallback_chain=["local_cache", "vendor"],
            fetched_at=datetime.now(timezone.utc),
            explicit_local=False,
        ),
        row_count=100,
        symbol_count=1,
        field_coverage={"close": 1.0},
        quality_warnings=[
            StructuredWarning(code="DATA_VALIDATOR_SAMPLED", message="sampled"),
        ],
    )


def _scorecard(conclusion_cap: str = "research_candidate") -> BacktestReliabilityScorecard:
    return BacktestReliabilityScorecard(
        scorecard_id="sc_1",
        schema_version="1.0.0",
        score=0.5,
        score_breakdown={key: 0.5 for key in SCORECARD_DIMENSION_KEYS},
        conclusion_cap=conclusion_cap,
        warnings=[QuantIssue(code="QUANT_OOS_MISSING", message="missing oos")],
        hard_failures=[],
    )


def test_card_builder_from_complete_artifact_graph() -> None:
    card = build_research_card(
        ResearchCardGraph(
            card_id="card_complete",
            title="Reversal Study",
            protocol=_protocol(),
            data_audits=[_data_audit()],
            policy_decisions=[
                PolicyDecision(
                    tool_name="backtest",
                    action="allow",
                    mode="enforce",
                    reasons=["allowed"],
                    rule_id="P100",
                )
            ],
            scorecard=_scorecard("research_candidate"),
            key_metrics={"sharpe": 1.1},
            backtest_refs=["run_1"],
        )
    )

    assert card.protocol_ref == "proto_hash"
    assert card.data_audit_refs == ["audit_1"]
    assert card.policy_decision_refs
    assert card.data_sources[0]["selected_source"] == "local_cache"
    assert card.scorecard is not None
    assert card.conclusion_level == "research_candidate"


def test_card_builder_missing_artifact_adds_warning() -> None:
    card = build_research_card(
        ResearchCardGraph(
            card_id="card_missing",
            title="Missing artifacts",
            missing_artifacts=["data_audit:audit_missing"],
            scorecard=_scorecard("research_candidate"),
        )
    )

    assert any(warning.code == "RESEARCH_CARD_ARTIFACT_MISSING" for warning in card.warnings)


def test_conclusion_cannot_exceed_scorecard_cap() -> None:
    card = build_research_card(
        ResearchCardGraph(
            card_id="card_cap",
            title="Cap test",
            scorecard=_scorecard("exploratory"),
            requested_conclusion_level="paper_trade_candidate",
            has_oos=True,
            has_cost_model=True,
            has_benchmark=True,
        )
    )

    assert card.conclusion_level == "exploratory"


def test_no_oos_caps_conclusion() -> None:
    card = build_research_card(
        ResearchCardGraph(
            card_id="card_no_oos",
            title="No OOS",
            scorecard=_scorecard("paper_trade_candidate"),
            requested_conclusion_level="paper_trade_candidate",
            has_oos=False,
            has_cost_model=True,
            has_benchmark=True,
        )
    )

    assert card.conclusion_level == "research_candidate"


def test_no_cost_model_caps_conclusion() -> None:
    card = build_research_card(
        ResearchCardGraph(
            card_id="card_no_cost",
            title="No cost model",
            scorecard=_scorecard("paper_trade_candidate"),
            requested_conclusion_level="paper_trade_candidate",
            has_oos=True,
            has_cost_model=False,
            has_benchmark=True,
        )
    )

    assert card.conclusion_level == "research_candidate"


def test_no_benchmark_prevents_alpha_claim() -> None:
    card = build_research_card(
        ResearchCardGraph(
            card_id="card_no_benchmark",
            title="No benchmark",
            scorecard=_scorecard("paper_trade_candidate"),
            requested_conclusion_level="paper_trade_candidate",
            has_oos=True,
            has_cost_model=True,
            has_benchmark=False,
            claims_alpha=True,
        )
    )

    assert card.conclusion_level == "research_candidate"
    assert any(warning.code == "RESEARCH_CARD_ALPHA_CLAIM_WITHOUT_BENCHMARK" for warning in card.warnings)


def test_pit_violation_caps_conclusion() -> None:
    card = build_research_card(
        ResearchCardGraph(
            card_id="card_pit",
            title="PIT violation",
            scorecard=_scorecard("paper_trade_candidate"),
            requested_conclusion_level="paper_trade_candidate",
            has_oos=True,
            has_cost_model=True,
            has_benchmark=True,
            has_pit_violation=True,
        )
    )

    assert card.conclusion_level == "research_candidate"


def test_builder_applies_hard_failure_gate() -> None:
    scorecard = _scorecard("paper_trade_candidate").model_copy(
        update={
            "hard_failures": [
                QuantIssue(
                    code="PIT_FUTURE_DATA",
                    severity="hard_failure",
                    message="future data",
                )
            ]
        }
    )

    card = build_research_card(
        ResearchCardGraph(
            card_id="card_hard_failure",
            title="Hard failure",
            scorecard=scorecard,
            requested_conclusion_level="paper_trade_candidate",
        )
    )

    assert card.conclusion_level == "not_reliable"
    assert card.hard_failures[0].code == "PIT_FUTURE_DATA"
