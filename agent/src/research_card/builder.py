"""Minimal Research Card artifact assembly for v1.2.1 claim/fact evidence."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from src.governance.evidence_index import EvidenceIndexStore
from src.reliability.artifacts.store import ArtifactStore
from src.reliability.claims.extractor import build_claim_set_from_research_card
from src.reliability.claims.model import ClaimSet
from src.reliability.quant.methodology_facts import MethodologyFactSet, build_methodology_fact_set
from src.reliability.quant.scorecard import BacktestReliabilityScorecard
from src.reliability.quant.scorecard_policy import PredicateInput, ScorecardPolicyEngine

SCHEMA_VERSION = "1.2.1"


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
) -> ResearchCardEvidenceArtifacts:
    """Build and persist ClaimSet and MethodologyFactSet artifacts for a card."""
    run_id = str(research_card.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("research_card.run_id is required")

    claim_set = build_claim_set_from_research_card(research_card)
    methodology_facts = build_methodology_fact_set(
        run_id=run_id,
        protocol=protocol,
        data_audit=data_audit,
        scorecard=scorecard,
        trial_ledger=trial_ledger,
        research_card=research_card,
        policy_decision_ids=policy_decision_ids,
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
    exported_card = dict(research_card)
    exported_card["conclusion_level"] = policy_result.scorecard.conclusion_level
    exported_card["hard_failures"] = list(policy_result.scorecard.hard_failures)
    exported_card["triggered_rules"] = [
        rule.model_dump(mode="json") for rule in policy_result.scorecard.triggered_rules
    ]
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
    if evidence_index is not None:
        index = evidence_index.get_or_create(run_id)
        _append_unique(index.claim_set_artifact_refs, claim_record.artifact_id)
        _append_unique(index.methodology_fact_artifact_refs, fact_record.artifact_id)
        evidence_index.write(index)
    return ResearchCardEvidenceArtifacts(
        run_id=run_id,
        research_card=exported_card,
        claim_set=claim_set,
        methodology_facts=methodology_facts,
        scorecard=policy_result.scorecard,
        claim_set_artifact_id=claim_record.artifact_id,
        methodology_fact_artifact_id=fact_record.artifact_id,
    )


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


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
