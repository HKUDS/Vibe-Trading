"""Research card and evidence API security regressions."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.evidence_routes import register_evidence_routes
from src.api.runs_routes import register_runs_routes
from src.reliability.artifacts.store import ArtifactStore
from src.reliability.artifacts.verifier import EvidenceVerifier


RAW_SECRET = "Bearer abcdefghijklmnopqrstuvwxyz123456"


def _runs_client(tmp_path: Path) -> TestClient:
    import sys
    import types

    module = types.SimpleNamespace()
    module.RUNS_DIR = tmp_path
    module.require_auth = lambda: None
    import api_server as real_api_server

    module.RunResponse = real_api_server.RunResponse
    module.BacktestMetrics = real_api_server.BacktestMetrics
    module.RAGSelection = real_api_server.RAGSelection
    module.Artifact = real_api_server.Artifact
    module.RunInfo = real_api_server.RunInfo
    module._validate_path_param = real_api_server._validate_path_param
    sys.modules["api_server"] = module
    app = FastAPI()
    register_runs_routes(app, require_auth=lambda: None)
    return TestClient(app)


def test_artifact_path_traversal_returns_404_not_500(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    app = FastAPI()
    register_evidence_routes(app, artifact_store_factory=lambda: store)
    client = TestClient(app)

    response = client.get("/research/artifacts/%2e%2e%2foutside/lineage")

    assert response.status_code in {404, 422}
    assert response.status_code != 500


def test_artifact_path_traversal_does_not_leak_absolute_path(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifact-root")
    app = FastAPI()
    register_evidence_routes(app, artifact_store_factory=lambda: store)
    client = TestClient(app)

    response = client.get("/research/artifacts/..%2F..%2Fsecret/lineage")

    assert str(tmp_path) not in response.text
    assert "Traceback" not in response.text


def test_encoded_dotdot_traversal_denied(tmp_path: Path) -> None:
    client = _runs_client(tmp_path)
    response = client.get("/runs/%2e%2e%2fsecret")

    assert response.status_code in {400, 404, 422}
    assert response.status_code != 500
    assert str(tmp_path) not in response.text


def test_symlink_escape_denied_if_artifact_root_contains_symlink(tmp_path: Path) -> None:
    from src.reliability.artifacts.store import resolve_under_root
    from src.reliability.errors import ArtifactPathError

    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "root" / "link"
    link.parent.mkdir()
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        return

    try:
        resolve_under_root(tmp_path / "root", Path("link") / "secret.json")
    except ArtifactPathError:
        return
    raise AssertionError("symlink escape was not denied")


def test_missing_artifact_safe_not_found(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    app = FastAPI()
    register_evidence_routes(app, artifact_store_factory=lambda: store)
    response = TestClient(app).get("/research/artifacts/missing/lineage")

    assert response.status_code == 404
    assert "artifact not found" in response.text


def test_runs_detail_redacts_raw_research_card_payload(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_secret"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
    (run_dir / "run_card.json").write_text(
        json.dumps(
            {
                "schema_version": "1.2.1",
                "api_key": "sk-live-abcdefghijklmnopqrstuvwxyz123456",
                "nested": {"authorization": RAW_SECRET},
                "claim_text": "token=super-secret-token-value",
            }
        ),
        encoding="utf-8",
    )

    response = _runs_client(tmp_path).get("/runs/run_secret")

    assert response.status_code == 200
    body = response.text
    assert "[REDACTED]" in body
    assert "sk-live-" not in body
    assert RAW_SECRET not in body
    assert "super-secret-token-value" not in body


def test_evidence_verify_response_redacts_secret_like_values(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    store = ArtifactStore(tmp_path / "artifacts")
    store.write_json(
        {"schema_version": "1.2.1", "run_id": "run_secret", "nested": {"token": RAW_SECRET}},
        artifact_type="research_card",
        generated_by="test",
        metadata={"run_id": "run_secret"},
    )
    report = EvidenceVerifier(artifact_store=store).verify("run_secret")

    dumped = report.model_dump_json()
    assert RAW_SECRET not in dumped
    assert "artifact:" in dumped
    assert ".token" in dumped


def test_secret_scan_reports_field_path_not_secret_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    store = ArtifactStore(tmp_path / "artifacts")
    store.write_json(
        {"schema_version": "1.2.1", "password": "correct-horse-battery-staple"},
        artifact_type="research_card",
        generated_by="test",
        metadata={"run_id": "run_scan"},
    )

    warnings = EvidenceVerifier(artifact_store=store).verify("run_scan").secret_leak_warnings

    assert warnings
    assert all("correct-horse" not in warning for warning in warnings)
