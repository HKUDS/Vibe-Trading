from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import api_server
from src.governance.decisions import PolicyDecision
from src.reliability.artifacts.store import ArtifactStore
from src.research_card.model import ResearchCard, StructuredFailure


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("VIBE_TRADING_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    monkeypatch.setattr(api_server, "RUNS_DIR", tmp_path / "runs")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_read_only_api_returns_card(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    card = ResearchCard(
        card_id="card_api",
        title="API Card",
        hard_failures=[StructuredFailure(code="PIT_FUTURE_DATA", message="future data")],
        conclusion_level="not_reliable",
    )
    ArtifactStore(root=tmp_path / "artifacts").write_json(
        card.model_dump(mode="json"),
        artifact_type="research_card",
        generated_by="test",
        metadata={"card_id": card.card_id},
        schema_version=card.schema_version,
    )

    response = client.get("/research/cards/card_api")

    assert response.status_code == 200
    assert response.json()["card_id"] == "card_api"
    assert response.json()["hard_failures"][0]["code"] == "PIT_FUTURE_DATA"


def test_policy_decisions_api_redacts_params(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    decision = PolicyDecision(
        tool_name="get_market_data",
        action="warn",
        mode="warn",
        reasons=["test"],
        rule_id="P50",
        params_preview={"api_key": "sk-test-secret-abcdefghijklmnopqrstuvwxyz", "symbol": "SPY"},
    )
    ArtifactStore(root=tmp_path / "artifacts").write_json(
        decision.model_dump(mode="json"),
        artifact_type="policy_decision",
        generated_by="test",
        metadata={"run_id": "run_1"},
        schema_version="1.0.0",
    )

    response = client.get("/governance/policy-decisions?run_id=run_1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.0.0"
    assert payload["decisions"][0]["params_preview"]["api_key"] == "[REDACTED]"
    assert payload["decisions"][0]["params_preview"]["symbol"] == "SPY"


def test_old_run_without_research_card_does_not_500(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "old_run"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        '{"status": "success", "created_at": "2026-01-01T00:00:00Z"}',
        encoding="utf-8",
    )

    response = client.get("/runs/old_run")

    assert response.status_code == 200
    assert response.json()["run_id"] == "old_run"
    assert response.json().get("research_card") is None


def test_research_artifact_and_protocol_read_endpoints(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    store = ArtifactStore(root=tmp_path / "artifacts")
    protocol = {
        "protocol_id": "proto_api",
        "schema_version": "1.0.0",
        "protocol_hash": "hash",
        "status": "registered",
        "hypothesis": "test",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "test",
    }
    record = store.write_json(
        protocol,
        artifact_type="research_protocol",
        generated_by="test",
        metadata={"protocol_id": "proto_api"},
        schema_version="1.0.0",
    )
    assert record is not None

    artifact_response = client.get(f"/research/artifacts/{record.artifact_id}")
    protocol_response = client.get("/research/protocols/proto_api")

    assert artifact_response.status_code == 200
    assert artifact_response.json()["artifact"]["artifact_id"] == record.artifact_id
    assert protocol_response.status_code == 200
    assert protocol_response.json()["protocol_id"] == "proto_api"


def test_tool_manifest_api_is_read_only(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.get("/governance/tool-manifest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.0.0"
    assert any(item["name"] == "bash" and item["risk_level"] == "R5_SHELL" for item in payload["tools"])
