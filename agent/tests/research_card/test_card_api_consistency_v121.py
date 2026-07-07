"""Phase 6 Research Card/API/Markdown consistency tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.evidence_routes import register_evidence_routes
from src.governance.evidence_index import EvidenceIndexStore
from src.governance.evidence_outbox import EvidenceOutbox
from src.reliability.artifacts.store import ArtifactStore
from src.research_card.builder import build_research_card_evidence_artifacts
from src.research_card.model import ResearchCard
from src.research_card.render_markdown import render_research_card_markdown


def test_research_card_api_markdown_identity_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    run_id = "run_phase6_consistency"
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    index_store = EvidenceIndexStore(tmp_path / "evidence_index.sqlite")
    outbox = EvidenceOutbox(tmp_path / "evidence_outbox.sqlite")
    policy_decision_id = "pd_phase6_denied"

    policy_record = artifact_store.write_json(
        {
            "schema_version": "1.2.1",
            "decision_id": policy_decision_id,
            "run_id": run_id,
            "tool_name": "fake_shell",
            "action": "deny",
            "status": "shadow_denied",
            "mode": "warn",
            "surface": "remote_api",
            "risk_level": "R5_SHELL",
            "reason_codes": ["R5_REMOTE_API_DENIED"],
            "evidence_identity": {
                "schema_version": "1.2.1",
                "decision_id": policy_decision_id,
                "policy_decision_artifact_id": "art_policy_phase6_card",
                "trace_event_id": "trace_phase6_card",
                "ledger_event_hash": "ledger_phase6_card",
                "run_id": run_id,
                "idempotency_key": "idem_phase6_card",
            },
        },
        artifact_type="policy_decision",
        generated_by="pytest",
        metadata={"run_id": run_id, "decision_id": policy_decision_id},
        schema_version="1.2.1",
        artifact_id="art_policy_phase6_card",
    )
    assert policy_record is not None
    index = index_store.get_or_create(run_id)
    index.policy_decision_ids = [policy_decision_id]
    index.policy_decision_artifact_refs = [policy_record.artifact_id]
    index.trace_event_refs = ["trace_phase6_card"]
    index.ledger_event_hashes = ["ledger_phase6_card"]
    index_store.write(index)

    result = build_research_card_evidence_artifacts(
        {
            "schema_version": "1.2.1",
            "run_id": run_id,
            "conclusion_level": "paper_trade_candidate",
            "structured_claims": [
                {
                    "claim_type": "tradable",
                    "claim_text": "The strategy is tradable.",
                    "source_ref": "research_card.structured_claims[0]",
                    "evidence_refs": ["art_scorecard_phase6_card"],
                }
            ],
        },
        artifact_store=artifact_store,
        evidence_index=index_store,
        scorecard={"run_id": run_id, "conclusion_level": "paper_trade_candidate"},
        policy_decision_ids=[policy_decision_id],
        evidence_outbox=outbox,
    )

    card = ResearchCard.model_validate(result.research_card)
    markdown = render_research_card_markdown(
        card,
        claim_set=result.claim_set,
        methodology_facts=result.methodology_facts,
        scorecard=result.scorecard,
    )

    app = FastAPI()
    register_evidence_routes(
        app,
        artifact_store_factory=lambda: artifact_store,
        index_store_factory=lambda: index_store,
        outbox_factory=lambda: outbox,
    )
    api_decisions = TestClient(app).get(f"/governance/policy-decisions?run_id={run_id}").json()

    assert result.research_card_artifact_id.startswith("art_")
    assert result.scorecard_artifact_id.startswith("art_")
    assert card.policy_decision_ids == [policy_decision_id]
    assert api_decisions["decision_ids"] == card.policy_decision_ids
    assert card.claim_set_ref == result.claim_set_artifact_id
    assert card.methodology_fact_ref == result.methodology_fact_artifact_id
    assert card.hard_failures == result.scorecard.hard_failures
    assert "tradable_claim_without_cost_model" in card.hard_failures
    assert card.evidence_closure_summary is not None
    assert card.evidence_closure_summary.passed is True
    assert all(rule.rule_id and rule.reason_code and rule.explanation and rule.evidence_refs for rule in card.triggered_rules)

    claim_ids = [claim.claim_id for claim in result.claim_set.claims]
    assert claim_ids
    assert policy_decision_id in markdown
    assert "tradable_claim_without_cost_model" in markdown
    assert result.scorecard.hard_failures[0] in markdown
    for claim_id in claim_ids:
        assert claim_id in markdown


def test_old_research_card_fixture_renders_without_phase6_fields() -> None:
    card = ResearchCard.model_validate(
        {
            "schema_version": "1.2",
            "run_id": "legacy_run",
            "hard_failures": None,
            "warnings": ["legacy warning"],
        }
    )

    markdown = render_research_card_markdown(card)

    assert card.hard_failures == []
    assert "Evidence Closure" in markdown
    assert "legacy warning" in markdown
