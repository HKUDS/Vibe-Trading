from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import scheduled_routes
from src.scheduled_research.store import ScheduledResearchJobStore


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store = ScheduledResearchJobStore(path=tmp_path / "scheduled_jobs.json")
    monkeypatch.setattr(scheduled_routes, "_scheduled_research_store", store)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_create_email_job_persists_report_format(client: TestClient):
    response = client.post(
        "/scheduled-runs",
        json={
            "id": "email-html",
            "prompt": "prepare the daily report",
            "schedule": "60000",
            "delivery_channel": "email",
            "delivery_target": "reader@example.test",
            "delivery_format": "html",
        },
    )

    assert response.status_code == 201
    assert response.json()["delivery_format"] == "html"

    listed = client.get("/scheduled-runs").json()
    assert listed[0]["delivery_format"] == "html"


def test_create_rejects_report_format_for_non_email_channel(client: TestClient):
    response = client.post(
        "/scheduled-runs",
        json={
            "id": "telegram-pdf",
            "prompt": "prepare the daily report",
            "schedule": "60000",
            "delivery_channel": "telegram",
            "delivery_target": "123",
            "delivery_format": "pdf",
        },
    )

    assert response.status_code == 422
    assert "only for email" in response.json()["detail"]
