"""Partial research remains available; failures never become successful runs."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import json
import threading

import pytest

from src.swarm.models import RunStatus, SwarmAgentSpec, SwarmRun, SwarmTask, TaskStatus, WorkerResult
from src.swarm.runtime import SwarmRuntime
from src.swarm.store import SwarmStore


def test_partial_upstream_reaches_synthesis_with_actual_status(tmp_path, monkeypatch):
    store = SwarmStore(base_dir=tmp_path)
    runtime = SwarmRuntime(policy=ToolPolicy.from_config(get_env_config()), store=store)
    seen = []

    def worker(agent_spec, upstream_summaries, **kwargs):
        if agent_spec.id == "risk":
            return WorkerResult(
                status="failed", summary="Observed volatility 20%; VaR unavailable.", error="data timeout"
            )
        seen.append(upstream_summaries["risk"])
        return WorkerResult(status="completed", summary="Hold. VaR remains unavailable.")

    monkeypatch.setattr("src.swarm.runtime.run_node", worker)
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
    runtime = SwarmRuntime(policy=ToolPolicy.from_config(get_env_config()), store=store)
    cancel = threading.Event()
    calls = []

    def worker(agent_spec, **kwargs):
        calls.append(agent_spec.id)
        cancel.set()
        return WorkerResult(status="completed", summary="Available research: revenue $26B.")

    monkeypatch.setattr("src.swarm.runtime.run_node", worker)
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


@pytest.mark.parametrize("source", ["independent", "consumer", "missing"])
def test_data_binding_requires_a_scheduled_upstream(source):
    from src.swarm.task_store import validate_dag

    tasks = [SwarmTask(id="independent", agent_id="data", prompt_template="Collect"),
             SwarmTask(id="consumer", agent_id="editor", prompt_template="Integrate",
                       input_from={"data": source})]
    with pytest.raises(ValueError, match="not upstream in the DAG"):
        validate_dag(tasks)


def test_transitive_and_fan_in_data_bindings_preserve_schedule():
    from src.swarm.task_store import topological_layers, validate_dag

    tasks = [SwarmTask(id="data", agent_id="data", prompt_template="Collect"),
             SwarmTask(id="other", agent_id="data", prompt_template="Collect other"),
             SwarmTask(id="analysis", agent_id="analyst", prompt_template="Analyze",
                       depends_on=["data"], input_from={"data": "data"}),
             SwarmTask(id="report", agent_id="editor", prompt_template="Integrate",
                       depends_on=["analysis", "other"],
                       input_from={"computed": "analysis", "original": "data", "other": "other"})]
    validate_dag(tasks)
    assert topological_layers(tasks) == [["data", "other"], ["analysis"], ["report"]]


def test_duplicate_task_ids_are_refused_before_graph_collapses():
    from src.swarm.task_store import validate_dag

    with pytest.raises(ValueError, match="Duplicate task ID"):
        validate_dag([SwarmTask(id="same", agent_id="data", prompt_template="Collect"),
                      SwarmTask(id="same", agent_id="analyst", prompt_template="Analyze")])


def test_runtime_refuses_unscheduled_data_binding_before_dispatch(tmp_path, monkeypatch):
    run = SwarmRun(
        id="bad-binding", preset_name="bad-binding", created_at="2026-11-14T00:00:00Z",
        agents=[SwarmAgentSpec(id="worker", role="Worker", system_prompt="Complete task")],
        tasks=[SwarmTask(id="producer", agent_id="worker", prompt_template="Collect"),
               SwarmTask(id="consumer", agent_id="worker", prompt_template="Summarize",
                         input_from={"data": "producer"})],
    )
    runtime = SwarmRuntime(policy=ToolPolicy.from_config(get_env_config()), store=SwarmStore(base_dir=tmp_path))
    monkeypatch.setattr("src.swarm.runtime.build_run_from_preset", lambda *args, **kwargs: run)
    monkeypatch.setattr(runtime, "_execute_run", lambda *args: pytest.fail("must not dispatch"))
    with pytest.raises(ValueError, match="declare its depends_on path"):
        runtime.start_run("bad-binding", {})
    assert not (tmp_path / run.id).exists()
