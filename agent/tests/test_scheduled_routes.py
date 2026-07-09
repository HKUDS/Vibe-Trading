"""Route-level contracts for the scheduled research endpoints.

Exercises the REST surface mounted by ``register_scheduled_routes``:
``POST /scheduled-runs`` (create), ``GET /scheduled-runs`` (list + filter),
and ``DELETE /scheduled-runs/{job_id}`` (cancel). Each test drives the app
through ``TestClient`` and asserts the persisted store state, so the route
wiring, validation, and status codes are covered end to end.

The store singleton is redirected to a per-test ``tmp_path`` file so nothing
touches the real runtime root, and the default ``TestClient`` client host
(``testclient``) is treated as a loopback caller, so ``require_auth`` passes
without a configured API key.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import scheduled_routes
from src.scheduled_research.models import JobStatus, ScheduledResearchJob
from src.scheduled_research.store import ScheduledResearchJobStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScheduledResearchJobStore:
    """Isolate the module-level store singleton onto a temp file."""
    isolated = ScheduledResearchJobStore(path=tmp_path / "scheduled_jobs.json")
    monkeypatch.setattr(scheduled_routes, "_scheduled_research_store", isolated)
    return isolated


@pytest.fixture
def client(store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _seed(store: ScheduledResearchJobStore, **overrides: object) -> ScheduledResearchJob:
    defaults: dict[str, object] = {
        "id": "job-seed",
        "prompt": "scan momentum names",
        "schedule": "60000",
        "next_run_at": 1_700_000_000_000,
        "status": JobStatus.PENDING,
        "created_at": 1_700_000_000_000,
    }
    defaults.update(overrides)
    job = ScheduledResearchJob(**defaults)  # type: ignore[arg-type]
    store.upsert(job)
    return job


def test_create_persists_job_and_returns_201(
    client: TestClient, store: ScheduledResearchJobStore
):
    response = client.post(
        "/scheduled-runs",
        json={
            "id": "daily-scan",
            "prompt": "rank S&P 500 by 12-1 momentum",
            "schedule": "0 9 * * *",
            "config": {"universe": "sp500"},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "daily-scan"
    assert body["status"] == "pending"
    assert body["config"] == {"universe": "sp500"}

    stored = store.get("daily-scan")
    assert stored is not None
    assert stored.prompt == "rank S&P 500 by 12-1 momentum"
    assert stored.schedule == "0 9 * * *"


def test_create_generates_id_and_defaults_next_run_when_omitted(
    client: TestClient, store: ScheduledResearchJobStore
):
    response = client.post(
        "/scheduled-runs",
        json={"prompt": "rebalance check", "schedule": "300000"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"]
    assert body["next_run_at"] > 0
    assert store.get(body["id"]) is not None


def test_create_rejects_malformed_schedule_with_422(
    client: TestClient, store: ScheduledResearchJobStore
):
    response = client.post(
        "/scheduled-runs",
        json={"prompt": "bad cron", "schedule": "0 99 * * *"},
    )

    assert response.status_code == 422
    assert store.list_jobs() == []


def test_list_returns_jobs_newest_first(
    client: TestClient, store: ScheduledResearchJobStore
):
    _seed(store, id="older", created_at=1_700_000_000_000)
    _seed(store, id="newer", created_at=1_700_000_500_000)

    response = client.get("/scheduled-runs")

    assert response.status_code == 200
    ids = [job["id"] for job in response.json()]
    assert ids == ["newer", "older"]


def test_list_filters_by_status(
    client: TestClient, store: ScheduledResearchJobStore
):
    _seed(store, id="pending-one", status=JobStatus.PENDING)
    _seed(store, id="done-one", status=JobStatus.COMPLETED)

    response = client.get("/scheduled-runs", params={"status": "completed"})

    assert response.status_code == 200
    body = response.json()
    assert [job["id"] for job in body] == ["done-one"]


def test_list_rejects_out_of_range_limit(client: TestClient):
    assert client.get("/scheduled-runs", params={"limit": 0}).status_code == 422
    assert client.get("/scheduled-runs", params={"limit": 500}).status_code == 422


def test_delete_removes_job_and_returns_204(
    client: TestClient, store: ScheduledResearchJobStore
):
    _seed(store, id="cancel-me")

    response = client.delete("/scheduled-runs/cancel-me")

    assert response.status_code == 204
    assert not response.content
    assert store.get("cancel-me") is None


def test_delete_unknown_job_returns_404(
    client: TestClient, store: ScheduledResearchJobStore
):
    response = client.delete("/scheduled-runs/never-existed")

    assert response.status_code == 404


def test_delete_rejects_unsafe_job_id(
    client: TestClient, store: ScheduledResearchJobStore
):
    # A single path segment that still fails the safe-id pattern (the dot is
    # outside ``[A-Za-z0-9_-]``) is rejected by the handler before any store
    # lookup, so it returns 400 rather than the 404 used for unknown ids.
    response = client.delete("/scheduled-runs/bad.id")

    assert response.status_code == 400
