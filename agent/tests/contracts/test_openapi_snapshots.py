"""Phase 6 API contract snapshots for evidence/card UI consumers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.evidence_routes import register_evidence_routes
from src.governance.evidence_index import EvidenceIndexStore
from src.governance.evidence_outbox import EvidenceOutbox
from src.reliability.artifacts.store import ArtifactStore


REQUIRED_GET_PATHS = {
    "/research/evidence/{run_id}",
    "/research/evidence/{run_id}/verify",
    "/research/artifacts/{artifact_id}/lineage",
    "/governance/policy-decisions",
    "/research/claims/{run_id}",
    "/research/methodology-facts/{run_id}",
}


def test_phase6_read_only_routes_are_get_only_in_openapi() -> None:
    import api_server

    schema = api_server.app.openapi()
    paths = schema["paths"]

    assert REQUIRED_GET_PATHS.issubset(paths)
    for path in REQUIRED_GET_PATHS:
        assert set(paths[path]) == {"get"}

    routes = {route.path: route.methods for route in api_server.app.routes if route.path in REQUIRED_GET_PATHS}
    assert set(routes) == REQUIRED_GET_PATHS
    assert all(methods == {"GET"} for methods in routes.values())


def test_phase6_contract_endpoints_return_secret_free_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    run_id = "run_phase6_contract"
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    index_store = EvidenceIndexStore(tmp_path / "evidence_index.sqlite")
    outbox = EvidenceOutbox(tmp_path / "evidence_outbox.sqlite")

    policy_record = artifact_store.write_json(
        {
            "schema_version": "1.2.1",
            "decision_id": "pd_remote_shell_denied",
            "run_id": run_id,
            "tool_name": "fake_shell",
            "action": "deny",
            "status": "shadow_denied",
            "mode": "warn",
            "surface": "remote_api",
            "risk_level": "R5_SHELL",
            "reason_codes": ["R5_REMOTE_API_DENIED"],
            "redacted_params_preview": {"api_key": "sk-live-should-not-leak"},
        },
        artifact_type="policy_decision",
        generated_by="pytest",
        metadata={"run_id": run_id, "decision_id": "pd_remote_shell_denied"},
        schema_version="1.2.1",
        artifact_id="art_policy_phase6",
    )
    assert policy_record is not None
    artifact_store.write_json(
        {
            "schema_version": "1.2.1",
            "claim_set_id": "claims_phase6",
            "run_id": run_id,
            "claims": [
                {
                    "schema_version": "1.2.1",
                    "claim_id": "claim_alpha_phase6",
                    "claim_type": "alpha",
                    "claim_text": "The run claims alpha.",
                    "source": "research_card",
                    "confidence": 0.95,
                    "requires_gate": True,
                    "evidence_refs": ["art_scorecard_phase6"],
                    "created_at": "2026-07-07T00:00:00Z",
                }
            ],
            "extractor_version": "deterministic-v1.2.1",
            "generated_by": "pytest",
            "artifact_ref": "art_claims_phase6",
        },
        artifact_type="claim_set",
        generated_by="pytest",
        metadata={"run_id": run_id, "claim_set_id": "claims_phase6"},
        schema_version="1.2.1",
        artifact_id="art_claims_phase6",
    )
    artifact_store.write_json(
        {
            "schema_version": "1.2.1",
            "run_id": run_id,
            "has_registered_protocol": True,
            "trial_count": 8,
            "has_data_audit": True,
            "pit_safe": True,
            "has_cost_model": False,
            "has_benchmark": False,
            "has_oos": True,
            "has_policy_denies": True,
            "policy_deny_ids": ["pd_remote_shell_denied"],
        },
        artifact_type="methodology_facts",
        generated_by="pytest",
        metadata={"run_id": run_id},
        schema_version="1.2.1",
        artifact_id="art_facts_phase6",
    )
    index = index_store.get_or_create(run_id)
    index.policy_decision_ids = ["pd_remote_shell_denied"]
    index.policy_decision_artifact_refs = ["art_policy_phase6"]
    index.claim_set_artifact_refs = ["art_claims_phase6"]
    index.methodology_fact_artifact_refs = ["art_facts_phase6"]
    index_store.write(index)

    app = FastAPI()
    register_evidence_routes(
        app,
        artifact_store_factory=lambda: artifact_store,
        index_store_factory=lambda: index_store,
        outbox_factory=lambda: outbox,
    )
    client = TestClient(app)

    policy_payload = client.get(f"/governance/policy-decisions?run_id={run_id}").json()
    claims_payload = client.get(f"/research/claims/{run_id}").json()
    facts_payload = client.get(f"/research/methodology-facts/{run_id}").json()

    assert policy_payload == {
        "schema_version": "1.2.1",
        "run_id": run_id,
        "decision_ids": ["pd_remote_shell_denied"],
        "decisions": [
            {
                "decision_id": "pd_remote_shell_denied",
                "tool_name": "fake_shell",
                "action": "deny",
                "status": "shadow_denied",
                "mode": "warn",
                "surface": "remote_api",
                "risk_level": "R5_SHELL",
                "reason_codes": ["R5_REMOTE_API_DENIED"],
                "evidence_refs": ["art_policy_phase6"],
                "trace_event_id": None,
                "ledger_event_hash": None,
            }
        ],
    }
    assert claims_payload["claim_set"]["claim_set_id"] == "claims_phase6"
    assert claims_payload["claim_ids"] == ["claim_alpha_phase6"]
    assert facts_payload["methodology_facts"]["trial_count"] == 8

    snapshot = json.dumps(
        {"policy": policy_payload, "claims": claims_payload, "facts": facts_payload},
        sort_keys=True,
    )
    assert "sk-live-should-not-leak" not in snapshot
    assert "api_key" not in snapshot
