"""Phase 10 schema migration and final packaging tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.evidence_routes import register_evidence_routes
from src.governance.evidence_index import EvidenceIndexStore
from src.reliability.artifacts.store import ArtifactStore
from src.reliability.artifacts.verifier import EvidenceVerifier
from src.reliability.quant.scorecard import BacktestReliabilityScorecard
from src.research_card.model import ResearchCard
from src.research_protocol.registry import ResearchProtocol

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _json_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_old_policy_decision_readable_without_evidence_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    payload = _json_fixture("policy_decision_v1_2.json")
    assert "evidence_identity" not in payload
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    artifact_store.write_json(
        payload,
        artifact_type="policy_decision",
        generated_by="migration_fixture",
        metadata={"run_id": payload["run_id"], "decision_id": payload["decision_id"]},
        schema_version=payload["schema_version"],
        artifact_id="art_legacy_policy_decision_v12",
    )

    app = FastAPI()
    register_evidence_routes(
        app,
        artifact_store_factory=lambda: artifact_store,
        index_store_factory=lambda: EvidenceIndexStore(tmp_path / "missing_index.sqlite"),
    )
    response = TestClient(app).get(f"/governance/policy-decisions?run_id={payload['run_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["decision_ids"] == [payload["decision_id"]]
    assert body["decisions"][0]["trace_event_id"] is None


def test_old_research_card_readable_without_claim_set_ref() -> None:
    payload = _json_fixture("research_card_v1_2.json")
    assert "claim_set_ref" not in payload

    card = ResearchCard.model_validate(payload)

    assert card.run_id == payload["run_id"]
    assert card.claim_set_ref is None
    assert card.hard_failures == payload["hard_failures"]


def test_old_scorecard_readable_without_triggered_rules_or_diagnostics() -> None:
    payload = _json_fixture("scorecard_v1_2.json")
    assert "triggered_rules" not in payload
    assert "diagnostics_readiness" not in payload

    scorecard = BacktestReliabilityScorecard.model_validate(payload)

    assert scorecard.run_id == payload["run_id"]
    assert scorecard.triggered_rules == []
    assert scorecard.diagnostics_readiness is None


def test_old_protocol_readable_without_confirmation_status() -> None:
    payload = _json_fixture("protocol_v1_2.json")
    provenance = payload["provenance"][0]
    assert "confirmation_status" not in provenance

    protocol = ResearchProtocol.model_validate(payload)

    assert protocol.protocol_id == payload["protocol_id"]
    assert protocol.provenance[0].confirmation_status == "not_required"


def test_old_run_without_index_returns_degraded_report_not_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    fixture_dir = FIXTURES / "run_without_evidence_index_v1_1"
    card = json.loads((fixture_dir / "research_card.json").read_text(encoding="utf-8"))
    scorecard = json.loads((fixture_dir / "scorecard.json").read_text(encoding="utf-8"))
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    artifact_store.write_json(
        scorecard,
        artifact_type="scorecard",
        generated_by="migration_fixture",
        metadata={"run_id": scorecard["run_id"]},
        schema_version=scorecard["schema_version"],
        artifact_id="art_legacy_scorecard_no_index",
    )
    artifact_store.write_json(
        card,
        artifact_type="research_card",
        generated_by="migration_fixture",
        metadata={"run_id": card["run_id"]},
        schema_version=card["schema_version"],
        artifact_id="art_legacy_card_no_index",
    )

    report = EvidenceVerifier(
        artifact_store=artifact_store,
        index_store=EvidenceIndexStore(tmp_path / "missing_index.sqlite"),
    ).verify(card["run_id"])

    assert report.passed is True
    assert report.degraded is True
    assert "index_missing_rebuilt_from_artifacts" in report.degraded_reasons
    assert "card" in report.verified_from
    assert "scorecard" in report.verified_from


def test_phase10_docs_exist_and_final_acceptance_contains_dod() -> None:
    docs = [
        "docs/irr-agl-v1.2.1-architecture.md",
        "docs/irr-agl-v1.2.1-demo-guide.md",
        "docs/irr-agl-v1.2.1-migration-guide.md",
        "docs/irr-agl-v1.2.1-threat-model-delta.md",
        "docs/irr-agl-v1.2.1-final-acceptance.md",
    ]
    for doc in docs:
        assert (ROOT / doc).is_file(), doc

    acceptance = (ROOT / "docs/irr-agl-v1.2.1-final-acceptance.md").read_text(encoding="utf-8")
    assert "22-item Definition of Done" in acceptance
    assert acceptance.count("- [x]") >= 22
    assert "pytest --tb=short -q --ignore=agent/tests/e2e_backtest" in acceptance
    assert "Rollback" in acceptance
    assert "Known Limitations" in acceptance
