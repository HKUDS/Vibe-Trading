from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.alpha_foundry.reports.builder import build_alpha_genesis_report
from src.alpha_quality.decision.model import AlphaQualityDecision, QualityDecision
from src.alpha_quality.model import AlphaQualityScorecard
from src.api.alpha_genesis_routes import register_alpha_genesis_routes


async def _noop_auth() -> None:
    return None


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VIBE_TRADING_ALPHA_GENESIS_REPORT_DIR", str(tmp_path))
    app = FastAPI()
    register_alpha_genesis_routes(app, require_auth=_noop_auth)
    return TestClient(app)


@pytest.mark.parametrize(
    "artifact_id",
    [
        "..%2f..%2f.env",
        "..%5c..%5cWindows%5cwin.ini",
        "%252e%252e%252f.env",
        "candidate%00",
        "candidate%0d%0aSet-Cookie:%20evil=1",
        "候选因子",
        "a" * 2_048,
        "scorecard?schema_version=alpha_quality_scorecard.v1",
    ],
)
def test_alpha_genesis_api_rejects_extreme_artifact_id_payloads(
    client: TestClient, tmp_path: Path, artifact_id: str
) -> None:
    response = client.get(f"/api/alpha-genesis/reports/{artifact_id}")

    assert response.status_code in {400, 404}
    assert "Traceback" not in response.text
    assert str(tmp_path) not in response.text
    assert "Set-Cookie: evil=1" not in response.text


def test_alpha_genesis_api_binds_endpoint_to_expected_schema(
    client: TestClient,
    tmp_path: Path,
) -> None:
    scorecard = AlphaQualityScorecard(
        factor_id="candidate",
        formula="rank(close)",
        factor_definition_hash="sha256:candidate",
    )
    (tmp_path / "candidate.scorecard.json").write_text(scorecard.to_json(), encoding="utf-8")

    scorecard_response = client.get("/api/alpha-genesis/scorecards/candidate")
    cross_type_response = client.get("/api/alpha-genesis/reports/candidate.scorecard")

    assert scorecard_response.status_code == 200
    assert scorecard_response.json()["schema_version"] == "alpha_quality_scorecard.v1"
    assert cross_type_response.status_code in {404, 422}
    assert "alpha_quality_scorecard" not in cross_type_response.text


def test_alpha_genesis_api_does_not_reflect_untrusted_headers(
    client: TestClient,
    tmp_path: Path,
) -> None:
    report = build_alpha_genesis_report(report_id="header-safe", candidate_id="candidate")
    (tmp_path / "header-safe.json").write_text(report.to_json(), encoding="utf-8")

    response = client.get(
        "/api/alpha-genesis/reports/header-safe",
        headers={
            "X-Forwarded-Host": "attacker.example",
            "X-Alpha-Genesis-Decision": "paper_candidate",
        },
    )

    assert response.status_code == 200
    assert "attacker.example" not in response.text
    assert response.json()["decision"] == "research_only"
    assert "attacker.example" not in "\n".join(f"{k}: {v}" for k, v in response.headers.items())


def test_alpha_genesis_quality_decision_query_cannot_forge_payload(
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
        total_quality_score=0.01,
    )
    (tmp_path / "candidate.decision.json").write_text(decision.to_json(), encoding="utf-8")

    response = client.get(
        "/api/alpha-genesis/quality-decisions/candidate",
        params={
            "schema_version": "alpha_quality_decision.v1",
            "decision": "forward_track",
            "total_quality_score": "999",
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "research_only"
    assert response.json()["total_quality_score"] == 0.01
