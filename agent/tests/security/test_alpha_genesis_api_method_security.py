from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.alpha_quality.decision.model import AlphaQualityDecision, QualityDecision
from src.api.alpha_genesis_routes import register_alpha_genesis_routes


async def _noop_auth() -> None:
    return None


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VIBE_TRADING_ALPHA_GENESIS_REPORT_DIR", str(tmp_path))
    app = FastAPI()
    register_alpha_genesis_routes(app, require_auth=_noop_auth)
    return TestClient(app)


def test_alpha_genesis_write_methods_are_rejected_without_artifact_side_effects(
    client: TestClient,
    tmp_path: Path,
) -> None:
    before = sorted(path.name for path in tmp_path.iterdir())

    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/alpha-genesis/reports/r1")
        assert response.status_code in {404, 405}

    after = sorted(path.name for path in tmp_path.iterdir())
    assert after == before


def test_caller_query_params_cannot_override_quality_decision(
    client: TestClient,
    tmp_path: Path,
) -> None:
    decision = AlphaQualityDecision(
        schema_version="alpha_quality_decision.v1",
        factor_id="candidate",
        decision=QualityDecision.RESEARCH_ONLY,
        hard_failures=[],
        warnings=[],
        cap_reasons=[],
        total_quality_score=0.1,
    )
    (tmp_path / "candidate.decision.json").write_text(decision.to_json(), encoding="utf-8")

    response = client.get(
        "/api/alpha-genesis/quality-decisions/candidate",
        params={"decision": "paper_candidate", "hard_failures": "[]"},
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "research_only"


def test_alpha_genesis_rejects_oversized_or_structured_ids(client: TestClient) -> None:
    for report_id in ("a" * 129, "null%00byte", "array[]", "object{}"):
        response = client.get(f"/api/alpha-genesis/reports/{report_id}")
        assert response.status_code == 400
        assert "Traceback" not in response.text


def test_corrupt_artifact_returns_sanitized_error(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{not-json", encoding="utf-8")

    response = client.get("/api/alpha-genesis/reports/bad")

    assert response.status_code == 500
    assert response.json() == {"detail": "alpha genesis artifact is invalid JSON"}
    assert str(tmp_path) not in response.text
    assert "Traceback" not in response.text
