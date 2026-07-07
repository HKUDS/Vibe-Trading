"""Build Research Cards from existing IRR-AGL artifacts and metadata."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.governance.decisions import PolicyDecision
from src.governance.evidence_index import EvidenceIndexStore, RunEvidenceIndex
from src.governance.evidence_outbox import EvidenceOutbox
from src.reliability.artifacts.store import ArtifactStore
from src.reliability.artifacts.verifier import EvidenceVerifier
from src.reliability.claims.extractor import build_claim_set_from_research_card
from src.reliability.claims.model import ClaimSet
from src.reliability.data.contracts import DataAuditReport, StructuredWarning as DataWarning
from src.reliability.quant.methodology_facts import MethodologyFactSet, build_methodology_fact_set
from src.reliability.quant.scorecard import BacktestReliabilityScorecard, QuantIssue
from src.reliability.quant.scorecard_policy import PredicateInput, ScorecardPolicyEngine
from src.research_card.model import (
    EvidenceClosureSummary,
    ResearchCard,
    StructuredFailure,
    StructuredWarning,
    evidence_closure_summary_from_report,
)
from src.research_protocol.model import ResearchProtocol

SCHEMA_VERSION = "1.2.1"

_CONCLUSION_RANK: dict[str, int] = {
    "not_reliable": 0,
    "exploratory": 1,
    "research_candidate": 2,
    "paper_trade_candidate": 3,
    "production_ready": 4,
}


class ResearchCardGraph(BaseModel):
    """Minimal artifact graph consumed by the Research Card builder."""

    model_config = ConfigDict(allow_inf_nan=False, arbitrary_types_allowed=True)

    card_id: str
    title: str
    protocol: ResearchProtocol | dict[str, Any] | None = None
    data_audits: list[DataAuditReport | dict[str, Any]] = Field(default_factory=list)
    policy_decisions: list[PolicyDecision | dict[str, Any]] = Field(default_factory=list)
    tool_trace_refs: list[str] = Field(default_factory=list)
    backtest_refs: list[str] = Field(default_factory=list)
    alpha_bench_refs: list[str] = Field(default_factory=list)
    scorecard: BacktestReliabilityScorecard | dict[str, Any] | None = None
    key_metrics: dict[str, Any] = Field(default_factory=dict)
    benchmark: dict[str, Any] = Field(default_factory=dict)
    cost_model: dict[str, Any] = Field(default_factory=dict)
    execution_assumptions: dict[str, Any] = Field(default_factory=dict)
    oos_results: dict[str, Any] = Field(default_factory=dict)
    reproducibility: dict[str, Any] = Field(default_factory=dict)
    requested_conclusion_level: str | None = None
    has_oos: bool | None = None
    has_cost_model: bool | None = None
    has_benchmark: bool | None = None
    has_pit_violation: bool = False
    claims_alpha: bool = False
    missing_artifacts: list[str] = Field(default_factory=list)


class ResearchCardEvidenceArtifacts(BaseModel):
    """Artifacts generated before Research Card export."""

    schema_version: str = SCHEMA_VERSION
    run_id: str
    research_card: dict[str, Any]
    claim_set: ClaimSet
    methodology_facts: MethodologyFactSet
    scorecard: BacktestReliabilityScorecard
    claim_set_artifact_id: str
    methodology_fact_artifact_id: str
    scorecard_artifact_id: str
    research_card_artifact_id: str


def build_research_card(graph: ResearchCardGraph) -> ResearchCard:
    """Build a Research Card without mutating existing run or artifact records."""
    protocol = _protocol(graph.protocol)
    data_audits = [_data_audit(item) for item in graph.data_audits]
    decisions = [_policy_decision(item) for item in graph.policy_decisions]
    scorecard = _scorecard(graph.scorecard)

    warnings: list[StructuredWarning | str] = []
    hard_failures: list[StructuredFailure | str] = []
    warnings.extend(_missing_artifact_warnings(graph.missing_artifacts))
    for audit in data_audits:
        warnings.extend(_warnings_from_data_audit(audit))
        for violation in audit.pit_violations:
            code = str(getattr(violation, "code", "") or getattr(violation, "violation_code", "") or "PIT_VIOLATION")
            warnings.append(StructuredWarning(code=code, message="PIT violation recorded"))
    if scorecard is not None:
        warnings.extend(_warnings_from_quant(scorecard.warnings))
        hard_failures.extend(_failures_from_quant(scorecard.hard_failures))

    if graph.claims_alpha and not _has_benchmark(graph, protocol):
        warnings.append(
            StructuredWarning(
                code="RESEARCH_CARD_ALPHA_CLAIM_WITHOUT_BENCHMARK",
                message="alpha claim requires benchmark evidence",
            )
        )

    conclusion = graph.requested_conclusion_level or "paper_trade_candidate"
    if scorecard is not None:
        conclusion = _min_conclusion(conclusion, scorecard.conclusion_cap)
    else:
        conclusion = _min_conclusion(conclusion, "exploratory")
        warnings.append(
            StructuredWarning(
                code="RESEARCH_CARD_SCORECARD_MISSING",
                message="research card has no quant reliability scorecard",
            )
        )
    if not _has_oos(graph, protocol, scorecard):
        conclusion = _min_conclusion(conclusion, "research_candidate")
    if not _has_cost_model(graph, protocol):
        conclusion = _min_conclusion(conclusion, "research_candidate")
    if not _has_benchmark(graph, protocol):
        conclusion = _min_conclusion(conclusion, "research_candidate")
    if graph.has_pit_violation or any(audit.pit_violations for audit in data_audits):
        conclusion = _min_conclusion(conclusion, "research_candidate")
    if hard_failures:
        conclusion = "not_reliable"

    decision_ids = [decision.decision_id for decision in decisions]
    return ResearchCard(
        card_id=graph.card_id,
        title=graph.title,
        protocol_ref=protocol.protocol_hash if protocol is not None else None,
        hypothesis=protocol.hypothesis if protocol is not None else None,
        universe=protocol.universe.model_dump(mode="json") if protocol is not None else {},
        data_sources=[_data_source_summary(audit) for audit in data_audits],
        data_audit_refs=[audit.audit_id for audit in data_audits],
        policy_decision_refs=decision_ids,
        policy_decision_ids=decision_ids,
        tool_trace_refs=list(graph.tool_trace_refs),
        backtest_refs=list(graph.backtest_refs),
        alpha_bench_refs=list(graph.alpha_bench_refs),
        scorecard=scorecard,
        key_metrics=dict(graph.key_metrics),
        benchmark=_benchmark(graph, protocol),
        cost_model=_cost_model(graph, protocol),
        execution_assumptions=_execution_assumptions(graph, protocol),
        oos_results=dict(graph.oos_results),
        warnings=warnings,
        hard_failures=hard_failures,
        reproducibility=dict(graph.reproducibility),
        conclusion_level=conclusion,
    )


def build_research_card_evidence_artifacts(
    research_card: dict[str, Any],
    *,
    artifact_store: ArtifactStore,
    evidence_index: EvidenceIndexStore | None = None,
    protocol: dict[str, Any] | None = None,
    data_audit: dict[str, Any] | None = None,
    scorecard: dict[str, Any] | None = None,
    trial_ledger: dict[str, Any] | None = None,
    policy_decision_ids: list[str] | None = None,
    evidence_outbox: EvidenceOutbox | None = None,
) -> ResearchCardEvidenceArtifacts:
    """Build and persist Research Card evidence artifacts from production builders."""
    run_id = str(research_card.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("research_card.run_id is required")

    index = evidence_index.get_or_create(run_id) if evidence_index is not None else RunEvidenceIndex(run_id=run_id)
    effective_policy_decision_ids = _dedupe([*(policy_decision_ids or []), *index.policy_decision_ids])
    claim_set = build_claim_set_from_research_card(research_card)
    methodology_facts = build_methodology_fact_set(
        run_id=run_id,
        protocol=protocol,
        data_audit=data_audit,
        scorecard=scorecard,
        trial_ledger=trial_ledger,
        research_card=research_card,
        policy_decision_ids=effective_policy_decision_ids,
    )
    raw_scorecard = _scorecard_from_input(scorecard, run_id=run_id, conclusion_level=research_card.get("conclusion_level"))
    policy_result = ScorecardPolicyEngine.default().evaluate(
        PredicateInput(
            scorecard=raw_scorecard,
            claim_set=claim_set,
            methodology_facts=methodology_facts,
            artifact_store=artifact_store,
        )
    )
    claim_record = artifact_store.write_json(
        claim_set.model_dump(mode="json"),
        artifact_type="claim_set",
        generated_by="research_card.builder",
        metadata={"run_id": run_id, "claim_set_id": claim_set.claim_set_id},
        schema_version=SCHEMA_VERSION,
    )
    fact_record = artifact_store.write_json(
        methodology_facts.model_dump(mode="json"),
        artifact_type="methodology_facts",
        generated_by="research_card.builder",
        metadata={"run_id": run_id},
        schema_version=SCHEMA_VERSION,
    )
    if claim_record is None or fact_record is None:
        raise RuntimeError("reliability artifacts are disabled; cannot export v1.2.1 research card evidence")
    claim_set.artifact_ref = claim_record.artifact_id
    policy_result.scorecard.claim_set_ref = claim_record.artifact_id
    policy_result.scorecard.methodology_fact_ref = fact_record.artifact_id
    policy_result.scorecard.policy_decision_ids = list(effective_policy_decision_ids)
    scorecard_record = artifact_store.write_json(
        policy_result.scorecard.model_dump(mode="json"),
        artifact_type="scorecard",
        generated_by="research_card.builder",
        metadata={"run_id": run_id},
        parent_artifacts=[claim_record.artifact_id, fact_record.artifact_id],
        schema_version=SCHEMA_VERSION,
    )
    if scorecard_record is None:
        raise RuntimeError("reliability artifacts are disabled; cannot export v1.2.1 scorecard evidence")

    if evidence_index is not None:
        _append_unique(index.claim_set_artifact_refs, claim_record.artifact_id)
        _append_unique(index.methodology_fact_artifact_refs, fact_record.artifact_id)
        _append_unique(index.scorecard_artifact_refs, scorecard_record.artifact_id)
        for decision_id in effective_policy_decision_ids:
            _append_unique(index.policy_decision_ids, decision_id)
        index.hard_failures = [str(item) for item in policy_result.scorecard.hard_failures]
        evidence_index.write(index)

    report = EvidenceVerifier(
        artifact_store=artifact_store,
        index_store=evidence_index,
        outbox=evidence_outbox,
    ).verify(run_id)
    exported_card = dict(research_card)
    exported_card["schema_version"] = SCHEMA_VERSION
    exported_card["conclusion_level"] = policy_result.scorecard.conclusion_level
    exported_card["hard_failures"] = list(policy_result.scorecard.hard_failures)
    exported_card["policy_decision_ids"] = list(effective_policy_decision_ids)
    exported_card["claim_set_ref"] = claim_record.artifact_id
    exported_card["methodology_fact_ref"] = fact_record.artifact_id
    exported_card["scorecard_ref"] = scorecard_record.artifact_id
    exported_card["claim_ids"] = [claim.claim_id for claim in claim_set.claims]
    exported_card["triggered_rules"] = [
        rule.model_dump(mode="json") for rule in policy_result.scorecard.triggered_rules
    ]
    exported_card["evidence_closure_summary"] = evidence_closure_summary_from_report(report).model_dump(mode="json")
    card_model = ResearchCard.model_validate(exported_card)
    if card_model.hard_failures != policy_result.scorecard.hard_failures:
        raise ValueError("Research Card hard_failures must exactly match scorecard hard_failures")
    card_record = artifact_store.write_json(
        card_model.model_dump(mode="json", exclude_none=True),
        artifact_type="research_card",
        generated_by="research_card.builder",
        metadata={"run_id": run_id},
        parent_artifacts=[claim_record.artifact_id, fact_record.artifact_id, scorecard_record.artifact_id],
        schema_version=SCHEMA_VERSION,
    )
    if card_record is None:
        raise RuntimeError("reliability artifacts are disabled; cannot export v1.2.1 research card")
    if evidence_index is not None:
        index = evidence_index.get_or_create(run_id)
        _append_unique(index.research_card_artifact_refs, card_record.artifact_id)
        evidence_index.write(index)

    return ResearchCardEvidenceArtifacts(
        run_id=run_id,
        research_card=card_model.model_dump(mode="json", exclude_none=True),
        claim_set=claim_set,
        methodology_facts=methodology_facts,
        scorecard=policy_result.scorecard,
        claim_set_artifact_id=claim_record.artifact_id,
        methodology_fact_artifact_id=fact_record.artifact_id,
        scorecard_artifact_id=scorecard_record.artifact_id,
        research_card_artifact_id=card_record.artifact_id,
    )


def _protocol(value: ResearchProtocol | dict[str, Any] | None) -> ResearchProtocol | None:
    if value is None:
        return None
    if isinstance(value, ResearchProtocol):
        return value
    return ResearchProtocol.model_validate(value)


def _data_audit(value: DataAuditReport | dict[str, Any]) -> DataAuditReport:
    if isinstance(value, DataAuditReport):
        return value
    return DataAuditReport.model_validate(value)


def _policy_decision(value: PolicyDecision | dict[str, Any]) -> PolicyDecision:
    if isinstance(value, PolicyDecision):
        return value
    return PolicyDecision.model_validate(value)


def _scorecard(value: BacktestReliabilityScorecard | dict[str, Any] | None) -> BacktestReliabilityScorecard | None:
    if value is None:
        return None
    if isinstance(value, BacktestReliabilityScorecard):
        return value
    return BacktestReliabilityScorecard.model_validate(value)


def _scorecard_from_input(
    scorecard: dict[str, Any] | BacktestReliabilityScorecard | None,
    *,
    run_id: str,
    conclusion_level: Any,
) -> BacktestReliabilityScorecard:
    if isinstance(scorecard, BacktestReliabilityScorecard):
        return scorecard
    payload = dict(scorecard or {})
    payload.setdefault("run_id", run_id)
    if conclusion_level is not None:
        payload.setdefault("conclusion_level", conclusion_level)
    return BacktestReliabilityScorecard.model_validate(payload)


def _warnings_from_data_audit(audit: DataAuditReport) -> list[StructuredWarning]:
    warnings: list[StructuredWarning] = []
    for item in [*audit.quality_warnings, *audit.market_rule_warnings]:
        warnings.append(_warning_from_data(item))
    if audit.all_sources_open:
        warnings.append(
            StructuredWarning(
                code="DATA_ALL_SOURCES_OPEN",
                severity="hard_failure",
                message="all fallback data sources were circuit-open",
            )
        )
    return warnings


def _warning_from_data(item: DataWarning) -> StructuredWarning:
    return StructuredWarning(code=item.code, severity=item.severity, message=item.message, metadata=item.metadata)


def _warnings_from_quant(items: list[QuantIssue | str]) -> list[StructuredWarning | str]:
    warnings: list[StructuredWarning | str] = []
    for item in items:
        if isinstance(item, QuantIssue):
            warnings.append(
                StructuredWarning(
                    code=item.code,
                    severity=item.severity,
                    message=item.message,
                    metadata=item.metadata,
                )
            )
        else:
            warnings.append(str(item))
    return warnings


def _failures_from_quant(items: list[QuantIssue | str]) -> list[StructuredFailure | str]:
    failures: list[StructuredFailure | str] = []
    for item in items:
        if isinstance(item, QuantIssue):
            failures.append(StructuredFailure(code=item.code, message=item.message, metadata=item.metadata))
        else:
            failures.append(str(item))
    return failures


def _missing_artifact_warnings(items: list[str]) -> list[StructuredWarning]:
    return [
        StructuredWarning(
            code="RESEARCH_CARD_ARTIFACT_MISSING",
            message="referenced artifact was unavailable while building research card",
            metadata={"artifact_ref": item},
        )
        for item in items
    ]


def _data_source_summary(audit: DataAuditReport) -> dict[str, Any]:
    access = audit.access_contract
    return {
        "audit_id": audit.audit_id,
        "source": access.source,
        "selected_source": access.selected_source,
        "fallback_chain": list(access.fallback_chain),
        "runtime_source": access.selected_source,
        "row_count": audit.row_count,
        "symbol_count": audit.symbol_count,
        "field_coverage": dict(audit.field_coverage),
        "all_sources_open": audit.all_sources_open,
    }


def _benchmark(graph: ResearchCardGraph, protocol: ResearchProtocol | None) -> dict[str, Any]:
    if graph.benchmark:
        return dict(graph.benchmark)
    if protocol is not None and protocol.benchmark_policy is not None:
        return protocol.benchmark_policy.model_dump(mode="json")
    return {}


def _cost_model(graph: ResearchCardGraph, protocol: ResearchProtocol | None) -> dict[str, Any]:
    if graph.cost_model:
        return dict(graph.cost_model)
    if protocol is not None and protocol.cost_model is not None:
        return protocol.cost_model.model_dump(mode="json")
    return {}


def _execution_assumptions(graph: ResearchCardGraph, protocol: ResearchProtocol | None) -> dict[str, Any]:
    if graph.execution_assumptions:
        return dict(graph.execution_assumptions)
    if protocol is not None and protocol.execution_assumptions is not None:
        return protocol.execution_assumptions.model_dump(mode="json")
    return {}


def _has_oos(
    graph: ResearchCardGraph,
    protocol: ResearchProtocol | None,
    scorecard: BacktestReliabilityScorecard | None,
) -> bool:
    if graph.has_oos is not None:
        return graph.has_oos
    if graph.oos_results:
        return True
    if scorecard is not None and scorecard.walk_forward is not None:
        return True
    if protocol is not None:
        return protocol.split_policy.method in {"walk_forward", "rolling", "expanding"} or bool(
            protocol.split_policy.test_start or protocol.split_policy.fold_count
        )
    return False


def _has_cost_model(graph: ResearchCardGraph, protocol: ResearchProtocol | None) -> bool:
    if graph.has_cost_model is not None:
        return graph.has_cost_model
    return bool(graph.cost_model or (protocol is not None and protocol.cost_model is not None))


def _has_benchmark(graph: ResearchCardGraph, protocol: ResearchProtocol | None) -> bool:
    if graph.has_benchmark is not None:
        return graph.has_benchmark
    return bool(graph.benchmark or (protocol is not None and protocol.benchmark_policy is not None))


def _min_conclusion(left: str, right: str) -> str:
    left_level = left if left in _CONCLUSION_RANK else "exploratory"
    right_level = right if right in _CONCLUSION_RANK else "exploratory"
    return min(left_level, right_level, key=lambda item: _CONCLUSION_RANK[item])


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped
