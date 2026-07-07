from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import api_server


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_server, "RUNS_DIR", tmp_path / "runs")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_run_detail_research_card_payload_redacts_secret_like_values(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "run_secret_card"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps({"status": "success", "created_at": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    (run_dir / "research_card.json").write_text(
        json.dumps(
            {
                "card_id": "card_secret",
                "schema_version": "1.0.0",
                "title": "Secret fixture",
                "hypothesis": "Authorization: Bearer fixture-token",
                "benchmark": {"primary": "sk-test-123456"},
                "cost_model": {"api_key": "sk-test-123456"},
                "warnings": [
                    {
                        "code": "SECRET_FIXTURE",
                        "message": "AWS_SECRET_ACCESS_KEY=fixture",
                    }
                ],
                "conclusion_level": "exploratory",
            }
        ),
        encoding="utf-8",
    )

    response = client.get("/runs/run_secret_card")

    assert response.status_code == 200
    raw = response.text
    assert "fixture-token" not in raw
    assert "sk-test-123456" not in raw
    assert "AWS_SECRET_ACCESS_KEY=fixture" not in raw
    assert "[REDACTED]" in raw
