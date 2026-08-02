"""Public swarm REST and SSE contract regressions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api_server
import src.api.swarm_routes as swarm_routes
from src.swarm.models import RunStatus, SwarmEvent, SwarmRun, SwarmTask
from src.swarm.store import SwarmStore


@pytest.fixture
def swarm_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SwarmStore:
    """Route the process-wide swarm endpoint at an isolated on-disk store."""
    store = SwarmStore(base_dir=tmp_path / "runs")
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    monkeypatch.setattr(swarm_routes, "_swarm_runtime", SimpleNamespace(_store=store))
    return store


def _client() -> TestClient:
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _create_run(
    store: SwarmStore,
    *,
    run_id: str = "run-contract",
    status: RunStatus = RunStatus.pending,
    tasks: list[SwarmTask] | None = None,
) -> SwarmRun:
    run = SwarmRun(
        id=run_id,
        preset_name="contract-test",
        status=status,
        created_at="2026-07-16T00:00:00+00:00",
        completed_at=("2026-07-16T00:00:01+00:00" if status == RunStatus.completed else None),
        tasks=tasks or [],
    )
    store.create_run(run)
    return run


def test_swarm_events_returns_404_before_streaming_missing_run(
    swarm_store: SwarmStore,
) -> None:
    response = _client().get("/swarm/runs/missing-run/events")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run missing-run not found"


def test_swarm_events_resumes_from_last_event_id_header(
    swarm_store: SwarmStore,
) -> None:
    run = _create_run(swarm_store, status=RunStatus.completed)
    for index in range(1, 4):
        swarm_store.append_event(
            run.id,
            SwarmEvent(
                type=f"step_{index}",
                data={"index": index},
                timestamp=f"2026-07-16T00:00:0{index}+00:00",
            ),
        )

    response = _client().get(
        f"/swarm/runs/{run.id}/events?last_index=1",
        headers={"Last-Event-ID": "2"},
    )

    assert response.status_code == 200
    assert "event: step_1" not in response.text
    assert "event: step_2" not in response.text
    assert "id: 3\nevent: step_3" in response.text
    assert 'event: done\ndata: {"status": "completed"}' in response.text


def test_swarm_events_keeps_last_index_query_compatibility(
    swarm_store: SwarmStore,
) -> None:
    run = _create_run(swarm_store, status=RunStatus.completed)
    for index in range(1, 3):
        swarm_store.append_event(
            run.id,
            SwarmEvent(
                type=f"query_step_{index}",
                timestamp=f"2026-07-16T00:00:0{index}+00:00",
            ),
        )

    response = _client().get(f"/swarm/runs/{run.id}/events?last_index=1")

    assert response.status_code == 200
    assert "event: query_step_1" not in response.text
    assert "id: 2\nevent: query_step_2" in response.text


def test_swarm_detail_uses_redacted_public_task_projection(
    swarm_store: SwarmStore,
) -> None:
    internal_path = str(Path.cwd() / "agent" / ".swarm" / "runs" / "secret" / "task.log")
    _create_run(
        swarm_store,
        tasks=[
            SwarmTask(
                id="task-1",
                agent_id="analyst",
                prompt_template="internal prompt",
                summary="Public summary",
                artifacts=[internal_path],
                error=f"failed while reading {internal_path}",
                worker_iterations=3,
            )
        ],
    )

    response = _client().get("/swarm/runs/run-contract")

    assert response.status_code == 200
    task = response.json()["tasks"][0]
    assert task["summary"] == "Public summary"
    assert "<redacted>" in task["error"]
    assert internal_path not in response.text
    assert "artifacts" not in task
    assert "prompt_template" not in task
    assert task["worker_iterations"] == 3
    assert task["iterations"] == 3
