"""FastAPI integration for versioned research artifacts."""

from __future__ import annotations

import hashlib
import json

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


def test_api_compares_revisions_and_rejects_cross_series(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    first = client.post("/api/research-artifacts", json=_payload()).json()["revision"]
    revised = client.post(
        "/api/research-artifacts",
        json=_payload(
            artifact_id=first["artifact_id"],
            content="Updated conclusion.",
            data_as_of="2026-11-03",
            evidence=[{"source_uri": "https://example.com/new"}],
        ),
    ).json()["revision"]

    response = client.get(
        f"/api/research-artifacts/{first['artifact_id']}/compare",
        params={"from_revision_id": first["revision_id"], "to_revision_id": revised["revision_id"]},
    )

    assert response.status_code == 200
    comparison = response.json()["comparison"]
    assert comparison["from"]["revision_id"] == first["revision_id"]
    assert comparison["to"]["revision_id"] == revised["revision_id"]
    assert comparison["content"]["changed"] is True
    assert comparison["evidence"]["added"] == [{"source_uri": "https://example.com/new"}]
    assert comparison["evidence"]["removed"] == [{"source_uri": "https://example.com/filing"}]
    assert comparison["metadata"]["data_as_of"] == {"from": "2026-10-20", "to": "2026-11-03"}

    other = client.post(
        "/api/research-artifacts",
        json=_payload(subject="MSFT review", universe="MSFT", content="Different research."),
    ).json()["revision"]
    cross_series = client.get(
        f"/api/research-artifacts/{first['artifact_id']}/compare",
        params={"from_revision_id": first["revision_id"], "to_revision_id": other["revision_id"]},
    )
    missing = client.get(
        f"/api/research-artifacts/{first['artifact_id']}/compare",
        params={"from_revision_id": first["revision_id"], "to_revision_id": "ra_missing_r1"},
    )
    assert cross_series.status_code == 404
    assert missing.status_code == 404

def test_api_exports_full_series_deterministically(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    first_response = client.post("/api/research-artifacts", json=_payload())
    assert first_response.status_code == 201
    artifact_id = first_response.json()["revision"]["artifact_id"]
    revised_response = client.post(
        "/api/research-artifacts",
        json=_payload(artifact_id=artifact_id, content="Updated conclusion.", data_as_of="2026-10-27"),
    )
    assert revised_response.status_code == 201

    exported = client.get(f"/api/research-artifacts/{artifact_id}/export", params={"format": "json"})
    repeated = client.get(f"/api/research-artifacts/{artifact_id}/export", params={"format": "json"})

    assert exported.status_code == 200
    assert exported.json() == repeated.json()
    body = exported.json()
    assert body["filename"] == f"{artifact_id}.json"
    assert body["media_type"] == "application/json"
    assert body["sha256"] == hashlib.sha256(body["content"].encode()).hexdigest()
    document = json.loads(body["content"])
    assert document["revision_count"] == 2
    assert document["revisions"][0]["content"] == "Original conclusion."

    markdown = client.get(f"/api/research-artifacts/{artifact_id}/export", params={"format": "markdown"})
    assert markdown.status_code == 200
    assert markdown.json()["filename"] == f"{artifact_id}.md"
    assert "Updated conclusion." in markdown.json()["content"]

    missing = client.get("/api/research-artifacts/ra_missing/export")
    invalid = client.get(f"/api/research-artifacts/{artifact_id}/export", params={"format": "xml"})
    assert missing.status_code == 404
    assert invalid.status_code == 422


def test_api_exports_selected_revision_comparison(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    first = client.post("/api/research-artifacts", json=_payload()).json()["revision"]
    revised = client.post(
        "/api/research-artifacts",
        json=_payload(
            artifact_id=first["artifact_id"],
            content="Updated conclusion.",
            data_as_of="2026-11-03",
            evidence=[{"source_uri": "https://example.com/new"}],
        ),
    ).json()["revision"]
    selection = {
        "from_revision_id": first["revision_id"],
        "to_revision_id": revised["revision_id"],
    }

    exported = client.get(
        f"/api/research-artifacts/{first['artifact_id']}/export",
        params={**selection, "format": "json"},
    )
    repeated = client.get(
        f"/api/research-artifacts/{first['artifact_id']}/export",
        params={**selection, "format": "json"},
    )
    markdown = client.get(
        f"/api/research-artifacts/{first['artifact_id']}/export",
        params={**selection, "format": "markdown"},
    )
    partial = client.get(
        f"/api/research-artifacts/{first['artifact_id']}/export",
        params={"from_revision_id": first["revision_id"]},
    )

    assert exported.status_code == 200
    assert exported.json() == repeated.json()
    body = exported.json()
    assert body["filename"] == f"{first['artifact_id']}-r1-r2.json"
    document = json.loads(body["content"])
    assert document["kind"] == "research_artifact_revision_comparison"
    assert document["comparison"]["from"]["revision_id"] == first["revision_id"]
    assert document["comparison"]["to"]["revision_id"] == revised["revision_id"]
    assert markdown.status_code == 200
    assert markdown.json()["filename"] == f"{first['artifact_id']}-r1-r2.md"
    assert "-Original conclusion." in markdown.json()["content"]
    assert "+Updated conclusion." in markdown.json()["content"]
    assert partial.status_code == 400
    assert "together" in partial.json()["detail"]

    other = client.post(
        "/api/research-artifacts",
        json=_payload(subject="MSFT review", universe="MSFT", content="Different research."),
    ).json()["revision"]
    cross_series = client.get(
        f"/api/research-artifacts/{first['artifact_id']}/export",
        params={**selection, "to_revision_id": other["revision_id"]},
    )
    assert cross_series.status_code == 404


def test_api_reports_missing_and_invalid_research_artifacts(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    missing = client.get("/api/research-artifacts/ra_missing")
    invalid = client.post("/api/research-artifacts", json=_payload(artifact_id="ra_missing"))
    blank = client.post("/api/research-artifacts", json=_payload(content=""))

    assert missing.status_code == 404
    assert invalid.status_code == 404
    assert blank.status_code == 422


def test_api_refuses_unbounded_evidence_and_ids(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    too_many = client.post("/api/research-artifacts", json=_payload(evidence=[{"source_uri": "u"}] * 1001))
    too_large = client.post("/api/research-artifacts", json=_payload(evidence=[{"note": "x" * 1_000_001}]))
    long_id = client.post("/api/research-artifacts", json=_payload(goal_id="g" * 201))
    at_limit = client.post("/api/research-artifacts", json=_payload(evidence=[{"source_uri": "u"}] * 1000))

    assert too_many.status_code == 422
    assert too_large.status_code == 422
    assert long_id.status_code == 422
    assert at_limit.status_code == 201
