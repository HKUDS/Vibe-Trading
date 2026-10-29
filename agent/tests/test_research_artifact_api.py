"""FastAPI integration for versioned research artifacts."""

from __future__ import annotations

from fastapi.testclient import TestClient

import api_server


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("VIBE_TRADING_RESEARCH_ARTIFACT_DB_PATH", str(tmp_path / "research.db"))
    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _payload(**overrides):
    payload = {
        "subject": "NVDA fundamental review",
        "universe": "NVDA",
        "content": "Original conclusion.",
        "data_as_of": "2026-10-20",
        "evidence": [{"source_uri": "https://example.com/filing"}],
        "verification_status": "verified",
        "goal_id": "goal-a",
    }
    payload.update(overrides)
    return payload


def test_api_save_search_and_revision_history(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    first_response = client.post("/api/research-artifacts", json=_payload())
    repeated_response = client.post("/api/research-artifacts", json=_payload())

    assert first_response.status_code == 201
    assert repeated_response.status_code == 201
    first = first_response.json()
    assert first["created"] is True
    assert repeated_response.json()["created"] is False

    artifact_id = first["revision"]["artifact_id"]
    revised_response = client.post(
        "/api/research-artifacts",
        json=_payload(artifact_id=artifact_id, content="Updated conclusion.", data_as_of="2026-10-27"),
    )
    assert revised_response.status_code == 201
    revised = revised_response.json()
    assert revised["revision"]["previous_revision_id"] == first["revision"]["revision_id"]

    searched = client.get("/api/research-artifacts", params={"query": "Updated conclusion"})
    assert searched.status_code == 200
    assert searched.json()["count"] == 1
    assert searched.json()["artifacts"][0]["evidence_missing"] is False

    detail = client.get(f"/api/research-artifacts/{artifact_id}")
    assert detail.status_code == 200
    assert len(detail.json()["revisions"]) == 2
    assert detail.json()["revisions"][-1]["content"] == "Original conclusion."

    old = client.get(f"/api/research-artifacts/revision/{first['revision']['revision_id']}")
    assert old.status_code == 200
    assert old.json()["revision"]["data_as_of"] == "2026-10-20"


def test_api_reports_missing_and_invalid_research_artifacts(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    missing = client.get("/api/research-artifacts/ra_missing")
    invalid = client.post("/api/research-artifacts", json=_payload(artifact_id="ra_missing"))
    blank = client.post("/api/research-artifacts", json=_payload(content=""))

    assert missing.status_code == 404
    assert invalid.status_code == 404
    assert blank.status_code == 422
