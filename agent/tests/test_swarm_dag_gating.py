"""Partial research remains available; failures never become successful runs."""

from __future__ import annotations

import json
import threading

from src.swarm.models import RunStatus, SwarmAgentSpec, SwarmRun, SwarmTask, TaskStatus, WorkerResult
from src.swarm.runtime import SwarmRuntime
from src.swarm.store import SwarmStore


def test_partial_upstream_reaches_synthesis_with_actual_status(tmp_path, monkeypatch):
    store = SwarmStore(base_dir=tmp_path)
    runtime = SwarmRuntime(store=store)
    seen = []

    def worker(agent_spec, upstream_summaries, **kwargs):
        if agent_spec.id == "risk":
            return WorkerResult(
                status="failed", summary="Observed volatility 20%; VaR unavailable.", error="data timeout"
            )
        seen.append(upstream_summaries["risk"])
        return WorkerResult(status="completed", summary="Hold. VaR remains unavailable.")

    monkeypatch.setattr("src.swarm.runtime.run_worker", worker)
    run = SwarmRun(
        id="partial",
        preset_name="demo",
        created_at="2026-11-13T00:00:00Z",
        agents=[SwarmAgentSpec(id=role, role=role, system_prompt="research", max_retries=0) for role in ("risk", "pm")],
        tasks=[
            SwarmTask(id="risk", agent_id="risk", prompt_template="analyze"),
            SwarmTask(
                id="pm", agent_id="pm", prompt_template="synthesize", depends_on=["risk"], input_from={"risk": "risk"}
            ),
        ],
    )
    store.create_run(run)
    runtime._execute_run(run, threading.Event())
    result = store.load_run(run.id)
    assert "failed" in seen[0] and "20%" in seen[0] and "data timeout" in seen[0]
    assert result.status == RunStatus.failed
    assert next(t for t in result.tasks if t.id == "pm").status == TaskStatus.completed
    assert result.final_report == "Hold. VaR remains unavailable."
    assert result.report_is_partial
    assert next(t for t in result.tasks if t.id == "risk").summary == "Observed volatility 20%; VaR unavailable."
    event = json.loads((tmp_path / run.id / "events.jsonl").read_text().splitlines()[-1])
    assert event["data"]["final_report"] == result.final_report
    assert event["data"]["report_is_partial"] is True


def test_user_cancellation_never_dispatches_remaining_roles(tmp_path, monkeypatch):
    store = SwarmStore(base_dir=tmp_path)
    runtime = SwarmRuntime(store=store)
    cancel = threading.Event()
    calls = []

    def worker(agent_spec, **kwargs):
        calls.append(agent_spec.id)
        cancel.set()
        return WorkerResult(status="completed", summary="Available research: revenue $26B.")

    monkeypatch.setattr("src.swarm.runtime.run_worker", worker)
    run = SwarmRun(
        id="cancel",
        preset_name="demo",
        created_at="2026-11-13T00:00:00Z",
        agents=[SwarmAgentSpec(id=role, role=role, system_prompt="x", max_retries=0) for role in ("a", "b")],
        tasks=[
            SwarmTask(id="a", agent_id="a", prompt_template="a"),
            SwarmTask(id="b", agent_id="b", prompt_template="b", depends_on=["a"]),
        ],
    )
    store.create_run(run)
    runtime._execute_run(run, cancel)
    result = store.load_run(run.id)
    assert calls == ["a"]
    assert result.status == RunStatus.cancelled
    assert result.report_is_partial
    assert "$26B" in result.final_report
    assert result.tasks[1].status == TaskStatus.cancelled
