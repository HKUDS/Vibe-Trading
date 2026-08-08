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
    assert body["last_run_at"] is None
    assert body["consecutive_failures"] == 0
    assert body["last_error"] is None
    assert body["failure_kind"] is None
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


def test_list_surfaces_retry_diagnostics(
    client: TestClient, store: ScheduledResearchJobStore
):
    _seed(
        store,
        id="retrying",
        status=JobStatus.PENDING,
        last_run_at=1_700_000_100_000,
        consecutive_failures=2,
        last_error="TimeoutError: provider timed out",
        failure_kind="dispatch",
    )

    response = client.get("/scheduled-runs")

    assert response.status_code == 200
    body = response.json()[0]
    assert body["last_run_at"] == 1_700_000_100_000
    assert body["consecutive_failures"] == 2
    assert body["last_error"] == "TimeoutError: provider timed out"
    assert body["failure_kind"] == "dispatch"


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


def test_create_with_timezone_echoes_and_persists(
    client: TestClient, store: ScheduledResearchJobStore
):
    response = client.post(
        "/scheduled-runs",
        json={
            "id": "auckland-scan",
            "prompt": "pre-open scan of NZX names",
            "schedule": "30 23 * * 1-5",
            "timezone": "Pacific/Auckland",
        },
    )

    assert response.status_code == 201
    assert response.json()["timezone"] == "Pacific/Auckland"

    saved = store.get("auckland-scan")
    assert saved is not None
    assert saved.timezone == "Pacific/Auckland"
    assert saved.schedule == "30 23 * * 1-5"


def test_create_without_timezone_defaults_to_null(
    client: TestClient, store: ScheduledResearchJobStore
):
    response = client.post(
        "/scheduled-runs",
        json={"id": "utc-scan", "prompt": "scan", "schedule": "0 9 * * *"},
    )

    assert response.status_code == 201
    body = response.json()
    assert "timezone" in body
    assert body["timezone"] is None
    saved = store.get("utc-scan")
    assert saved is not None
    assert saved.timezone is None


def test_create_rejects_unknown_timezone(
    client: TestClient, store: ScheduledResearchJobStore
):
    response = client.post(
        "/scheduled-runs",
        json={
            "id": "bad-tz",
            "prompt": "scan",
            "schedule": "0 9 * * *",
            "timezone": "Not/AZone",
        },
    )

    assert response.status_code == 422
    assert "IANA timezone" in response.json()["detail"]
    assert store.get("bad-tz") is None


def test_list_includes_timezone(client: TestClient, store: ScheduledResearchJobStore):
    _seed(store, id="tz-listed", schedule="0 9 * * 1-5", timezone="Australia/Adelaide")

    response = client.get("/scheduled-runs")

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()}
    assert rows["tz-listed"]["timezone"] == "Australia/Adelaide"


def test_create_tz_cron_defaults_next_run_to_first_authored_occurrence(
    client: TestClient, store: ScheduledResearchJobStore
):
    from src.scheduled_research.executor import next_due

    before = int(__import__("time").time() * 1000)
    response = client.post(
        "/scheduled-runs",
        json={
            "id": "first-occurrence",
            "prompt": "scan",
            "schedule": "30 23 * * 1-5",
            "timezone": "Pacific/Auckland",
        },
    )
    after = int(__import__("time").time() * 1000)

    assert response.status_code == 201
    next_run_at = response.json()["next_run_at"]
    # The first fire is the first authored wall-clock occurrence, which for a
    # 23:30 weekday cadence is strictly in the future — never "now".
    assert next_run_at > after
    assert next_due("30 23 * * 1-5", before, "Pacific/Auckland") <= next_run_at
    assert next_run_at <= next_due("30 23 * * 1-5", after, "Pacific/Auckland")


def test_create_without_timezone_keeps_immediate_first_fire(
    client: TestClient, store: ScheduledResearchJobStore
):
    before = int(__import__("time").time() * 1000)
    response = client.post(
        "/scheduled-runs",
        json={"id": "legacy-default", "prompt": "scan", "schedule": "0 9 * * *"},
    )
    after = int(__import__("time").time() * 1000)

    assert response.status_code == 201
    assert before <= response.json()["next_run_at"] <= after


def test_create_interval_with_timezone_keeps_immediate_first_fire(
    client: TestClient, store: ScheduledResearchJobStore
):
    before = int(__import__("time").time() * 1000)
    response = client.post(
        "/scheduled-runs",
        json={
            "id": "interval-tz",
            "prompt": "scan",
            "schedule": "60000",
            "timezone": "Pacific/Auckland",
        },
    )
    after = int(__import__("time").time() * 1000)

    assert response.status_code == 201
    assert before <= response.json()["next_run_at"] <= after


def test_create_rejects_ids_the_delete_route_would_refuse(
    client: TestClient, store: ScheduledResearchJobStore
):
    for bad_id in ("my scan.v1", "a/b", "café", "x" * 129):
        response = client.post(
            "/scheduled-runs",
            json={"id": bad_id, "prompt": "scan", "schedule": "60000"},
        )
        assert response.status_code == 422, bad_id
        assert "job id" in response.json()["detail"]
        assert store.get(bad_id) is None


def test_created_job_is_always_deletable(
    client: TestClient, store: ScheduledResearchJobStore
):
    created = client.post(
        "/scheduled-runs",
        json={"prompt": "scan", "schedule": "60000"},
    )
    assert created.status_code == 201
    job_id = created.json()["id"]

    assert client.delete(f"/scheduled-runs/{job_id}").status_code == 204
    assert store.get(job_id) is None


def test_create_accepts_ids_within_the_id_rule(
    client: TestClient, store: ScheduledResearchJobStore
):
    for good_id in ("daily-scan", "scan_2026", "A" * 128):
        response = client.post(
            "/scheduled-runs",
            json={"id": good_id, "prompt": "scan", "schedule": "60000"},
        )
        assert response.status_code == 201, good_id
        assert client.delete(f"/scheduled-runs/{good_id}").status_code == 204
def test_create_interval_accepts_a_timezone_it_will_never_use(
    client: TestClient, store: ScheduledResearchJobStore
):
    # The composer attaches the browser zone to every create. An interval
    # schedule ignores it, and the executor never resolves it, so a key this
    # host cannot resolve must not block the create.
    response = client.post(
        "/scheduled-runs",
        json={
            "id": "interval-unknown-zone",
            "prompt": "scan",
            "schedule": "60000",
            "timezone": "Mars/Olympus_Mons",
        },
    )

    assert response.status_code == 201
    saved = store.get("interval-unknown-zone")
    assert saved is not None
    assert saved.timezone == "Mars/Olympus_Mons"


def test_create_cron_still_rejects_an_unresolvable_timezone(
    client: TestClient, store: ScheduledResearchJobStore
):
    response = client.post(
        "/scheduled-runs",
        json={
            "id": "cron-unknown-zone",
            "prompt": "scan",
            "schedule": "0 9 * * *",
            "timezone": "Mars/Olympus_Mons",
        },
    )

    assert response.status_code == 422
    assert "IANA timezone" in response.json()["detail"]
    assert store.get("cron-unknown-zone") is None


def test_create_rejects_a_blank_timezone_for_both_schedule_forms(
    client: TestClient, store: ScheduledResearchJobStore
):
    for schedule in ("60000", "0 9 * * *"):
        response = client.post(
            "/scheduled-runs",
            json={"prompt": "scan", "schedule": schedule, "timezone": "   "},
        )
        assert response.status_code == 422, schedule
