"""Tests for swarm run replay (#1157): resuming a failed/cancelled run keeps
completed upstream tasks (with re-homed artifacts) and re-executes only the
failed/cancelled subgraph.

The overlay is exercised through the real orchestration loop
(``_execute_run``) with a fake worker, mirroring ``test_swarm_dag_gating.py``.
"""

from __future__ import annotations

import json
import threading

import pytest

import src.swarm.runtime as rt
from src.swarm.models import (
    RunStatus,
    SwarmAgentSpec,
    SwarmRun,
    SwarmTask,
    TaskStatus,
    WorkerResult,
)
from src.swarm.store import SwarmStore
from src.swarm.task_store import TaskStore


def _make_dag_run(run_id: str, status: RunStatus) -> SwarmRun:
    """A three-task DAG: t-a and t-b (layer 1), t-c consuming both (layer 2)."""
    agents = [
        SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="x", max_retries=0),
        SwarmAgentSpec(id="scout", role="Scout", system_prompt="x", max_retries=0),
        SwarmAgentSpec(id="pm", role="PM", system_prompt="x", max_retries=0),
    ]
    tasks = [
        SwarmTask(id="t-a", agent_id="analyst", prompt_template="do a"),
        SwarmTask(id="t-b", agent_id="scout", prompt_template="do b"),
        SwarmTask(
            id="t-c",
            agent_id="pm",
            prompt_template="do c",
            depends_on=["t-a", "t-b"],
            blocked_by=["t-a", "t-b"],
            input_from={"a": "t-a", "b": "t-b"},
        ),
    ]
    run = SwarmRun(
        id=run_id,
        preset_name="demo",
        created_at="2026-08-20T09:00:00+00:00",
        agents=agents,
        tasks=tasks,
    )
    run.status = status
    return run


def _seed_original_run(store: SwarmStore, run: SwarmRun) -> None:
    """Persist a failed/cancelled run: t-a completed (with an artifact),
    t-b failed, t-c blocked."""
    store.create_run(run)
    task_store = TaskStore(store.run_dir(run.id))
    for task in run.tasks:
        task_store.save_task(task)
    task_store.update_status(
        "t-a",
        TaskStatus.completed,
        summary="AAPL BUY 5 conviction",
        completed_at="2026-08-20T09:01:00+00:00",
        artifacts=["artifacts/analyst/report.md", "../outside.md"],
        worker_iterations=3,
    )
    artifact_file = store.run_dir(run.id) / "artifacts" / "analyst" / "report.md"
    artifact_file.parent.mkdir(parents=True, exist_ok=True)
    artifact_file.write_text("# kept report", encoding="utf-8")
    task_store.update_status(
        "t-b",
        TaskStatus.failed,
        error="mock data rejected",
        completed_at="2026-08-20T09:01:30+00:00",
    )
    task_store.update_status(
        "t-c",
        TaskStatus.blocked,
        error="Blocked: upstream not completed (t-b=failed)",
        blocked_by=["t-b"],
    )


@pytest.fixture
def workers_succeed(monkeypatch):
    """Every worker invocation succeeds; record (task_id, upstream) calls."""

    def fake_worker(agent_spec, task, upstream_summaries=None, **kwargs):
        workers_succeed.calls.append((task.id, dict(upstream_summaries or {})))
        return WorkerResult(
            status="completed",
            summary=f"fresh-{task.id}",
            artifact_paths=[],
            iterations=1,
            input_tokens=0,
            output_tokens=0,
        )

    workers_succeed.calls = []
    monkeypatch.setattr(rt, "run_worker", fake_worker)
    return workers_succeed


@pytest.mark.parametrize("orig_status", [RunStatus.failed, RunStatus.cancelled])
def test_replay_keeps_completed_upstream_and_reruns_subgraph(
    tmp_path, workers_succeed, orig_status
):
    """t-a is carried over untouched; t-b and t-c re-execute; t-c sees the
    kept summary as upstream context."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", orig_status)
    _seed_original_run(store, original)

    fresh = _make_dag_run("r-new", RunStatus.pending)
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    reloaded = store.load_run("r-new")
    assert reloaded is not None
    assert reloaded.status == RunStatus.completed

    by_id = {t.id: t for t in reloaded.tasks}
    assert by_id["t-a"].status == TaskStatus.completed
    assert by_id["t-a"].summary == "AAPL BUY 5 conviction", (
        "kept task must preserve the original summary, not re-execute"
    )
    # Only the contained artifact is re-homed into the new run; the escaped
    # path is dropped.
    assert by_id["t-a"].artifacts == ["artifacts/analyst/report.md"]
    rehomed = store.run_dir("r-new") / "artifacts" / "analyst" / "report.md"
    assert rehomed.is_file(), "kept artifact must be copied into the new run dir"
    assert (store.run_dir("r-orig") / "artifacts" / "analyst" / "report.md").is_file(), (
        "the original run must stay untouched as a record"
    )
    assert by_id["t-b"].status == TaskStatus.completed
    assert by_id["t-b"].summary == "fresh-t-b", "failed task must re-execute"
    assert by_id["t-c"].status == TaskStatus.completed
    assert by_id["t-c"].summary == "fresh-t-c"

    # t-a was never dispatched; t-b and t-c ran, in DAG order.
    called = [tid for tid, _ in workers_succeed.calls]
    assert called == ["t-b", "t-c"], f"unexpected worker calls: {called}"
    t_c_upstream = dict(workers_succeed.calls[1][1])
    assert t_c_upstream.get("a") == "AAPL BUY 5 conviction", (
        "re-executed dependent must receive the kept task's summary"
    )
    assert t_c_upstream.get("b") == "fresh-t-b"


def test_replay_emits_task_resumed_event(tmp_path, workers_succeed):
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", RunStatus.failed)
    _seed_original_run(store, original)

    fresh = _make_dag_run("r-new", RunStatus.pending)
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    events_file = tmp_path / "r-new" / "events.jsonl"
    events = [json.loads(line) for line in events_file.read_text().splitlines() if line.strip()]
    resumed = [e for e in events if e.get("type") == "task_resumed"]
    assert len(resumed) == 1
    assert resumed[0]["task_id"] == "t-a"
    assert resumed[0]["data"]["source_run_id"] == "r-orig"
    assert resumed[0].get("agent_id") == "analyst"


def test_replay_missing_prior_task_store_runs_fresh(tmp_path, workers_succeed):
    """A resume_from run whose task files are gone degrades to a full re-run."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", RunStatus.failed)
    store.create_run(original)  # run.json only — no task files

    fresh = _make_dag_run("r-new", RunStatus.pending)
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    reloaded = store.load_run("r-new")
    assert reloaded is not None
    assert reloaded.status == RunStatus.completed
    by_id = {t.id: t for t in reloaded.tasks}
    assert by_id["t-a"].summary == "fresh-t-a", (
        "no kept tasks => every task re-executes"
    )
    assert [tid for tid, _ in workers_succeed.calls] == ["t-a", "t-b", "t-c"]


def test_replay_seeds_empty_kept_summary(tmp_path, workers_succeed):
    """A kept task with an empty summary still seeds its input_from key, so a
    re-executed dependent sees an empty-string upstream (matching live runs)."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", RunStatus.failed)
    store.create_run(original)
    task_store = TaskStore(store.run_dir(original.id))
    for task in original.tasks:
        task_store.save_task(task)
    task_store.update_status(
        "t-a", TaskStatus.completed, summary="", completed_at="2026-08-20T09:01:00+00:00"
    )
    task_store.update_status("t-b", TaskStatus.failed, error="mock data rejected")
    task_store.update_status("t-c", TaskStatus.blocked, error="upstream failed")

    fresh = _make_dag_run("r-new", RunStatus.pending)
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    t_c_upstream = dict(workers_succeed.calls[-1][1])
    assert "a" in t_c_upstream, "empty kept summary must still seed the input_from key"
    assert t_c_upstream["a"] == ""


def test_replay_does_not_keep_changed_task_definition(tmp_path, workers_succeed):
    """A completed task whose definition changed since the original run must be
    re-executed, not kept — a kept result must still mean the same thing."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", RunStatus.failed)
    _seed_original_run(store, original)

    fresh = _make_dag_run("r-new", RunStatus.pending)
    # Redefine t-a's prompt (definition changed) — everything else identical.
    for task in fresh.tasks:
        if task.id == "t-a":
            task.prompt_template = "do a, but differently"
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    by_id = {t.id: t for t in store.load_run("r-new").tasks}
    assert by_id["t-a"].status == TaskStatus.completed
    assert by_id["t-a"].summary == "fresh-t-a", (
        "changed task definition must re-execute, not keep the old result"
    )
    assert [tid for tid, _ in workers_succeed.calls] == ["t-a", "t-b", "t-c"]


def test_replay_rehomes_only_artifacts_subtree(tmp_path, workers_succeed):
    """Control-file paths stored as artifacts (run.json, tasks/*, absolute) must
    be dropped: they must never clobber the new run's own state files."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", RunStatus.failed)
    store.create_run(original)
    task_store = TaskStore(store.run_dir(original.id))
    for task in original.tasks:
        task_store.save_task(task)
    task_store.update_status(
        "t-a",
        TaskStatus.completed,
        summary="KEPT",
        completed_at="2026-08-20T09:01:00+00:00",
        artifacts=["run.json", "tasks/task-t-b.json", "/etc/passwd", "artifacts/analyst/report.md"],
    )
    report = store.run_dir(original.id) / "artifacts" / "analyst" / "report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("# kept report", encoding="utf-8")
    task_store.update_status("t-b", TaskStatus.failed, error="mock data rejected")
    task_store.update_status("t-c", TaskStatus.blocked, error="upstream failed")

    fresh = _make_dag_run("r-new", RunStatus.pending)
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    by_id = {t.id: t for t in store.load_run("r-new").tasks}
    assert by_id["t-a"].artifacts == ["artifacts/analyst/report.md"], (
        f"control-file paths must be dropped, got {by_id['t-a'].artifacts}"
    )
    # The new run's own state file still parses as the new run's state.
    reloaded = store.load_run("r-new")
    assert reloaded is not None and reloaded.id == "r-new"
    assert reloaded.status == RunStatus.completed


def test_replay_artifact_destination_symlink_escape_blocked(tmp_path, workers_succeed):
    """A symlink planted in the new run's artifact tree must not redirect a
    re-homed artifact outside the run directory."""
    outside = tmp_path / "outside"
    outside.mkdir()
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", RunStatus.failed)
    _seed_original_run(store, original)

    fresh = _make_dag_run("r-new", RunStatus.pending)
    store.create_run(fresh)
    # Plant a symlink where the re-home would create the agent artifact dir.
    (store.run_dir("r-new") / "artifacts" / "analyst").symlink_to(
        outside, target_is_directory=True
    )

    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    by_id = {t.id: t for t in store.load_run("r-new").tasks}
    assert by_id["t-a"].artifacts == [], (
        "artifact re-home must refuse a destination that escapes the run dir"
    )
    assert list(outside.iterdir()) == [], "nothing may be written outside the run dir"


def test_replay_cancel_before_first_layer_keeps_completed_tasks(tmp_path, workers_succeed):
    """A cancellation signalled before layer 0 must not relabel kept tasks as
    cancelled — the in-memory task list is synced from the store after the
    overlay, so _cancel_remaining_tasks sees kept tasks as completed."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", RunStatus.failed)
    _seed_original_run(store, original)

    fresh = _make_dag_run("r-new", RunStatus.pending)
    store.create_run(fresh)
    cancel_event = threading.Event()
    cancel_event.set()  # cancel BEFORE the first layer's cancel check
    runtime._execute_run(fresh, cancel_event, resume_from=original)

    by_id = {t.id: t for t in store.load_run("r-new").tasks}
    assert by_id["t-a"].status == TaskStatus.completed, (
        f"kept task must survive cancellation, got {by_id['t-a'].status}"
    )
    assert by_id["t-a"].summary == "AAPL BUY 5 conviction"
    assert by_id["t-b"].status == TaskStatus.cancelled
    assert by_id["t-c"].status == TaskStatus.cancelled


def test_replay_keeps_completed_task_in_later_layer(tmp_path, workers_succeed):
    """Completed tasks in later layers are kept when their upstreams are kept;
    only the failed task re-executes."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    agents = [
        SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="x", max_retries=0),
        SwarmAgentSpec(id="pm", role="PM", system_prompt="x", max_retries=0),
    ]
    original = SwarmRun(
        id="r-orig",
        preset_name="demo",
        created_at="2026-08-20T09:00:00+00:00",
        agents=agents,
        tasks=[
            SwarmTask(id="t-x", agent_id="analyst", prompt_template="do x"),
            SwarmTask(
                id="t-y",
                agent_id="pm",
                prompt_template="do y",
                depends_on=["t-x"],
                blocked_by=["t-x"],
                input_from={"x": "t-x"},
            ),
            SwarmTask(
                id="t-z",
                agent_id="pm",
                prompt_template="do z",
                depends_on=["t-y"],
                blocked_by=["t-y"],
                input_from={"y": "t-y"},
            ),
        ],
    )
    original.status = RunStatus.failed
    store.create_run(original)
    task_store = TaskStore(store.run_dir(original.id))
    for task in original.tasks:
        task_store.save_task(task)
    # DAG-gated shape: t-x and t-y completed, the run failed at the last task.
    task_store.update_status(
        "t-x",
        TaskStatus.completed,
        summary="KEPT-X",
        completed_at="2026-08-20T09:01:00+00:00",
        artifacts=[],
    )
    task_store.update_status(
        "t-y",
        TaskStatus.completed,
        summary="KEPT-LAYER2",
        completed_at="2026-08-20T09:02:00+00:00",
        artifacts=[],
    )
    task_store.update_status("t-z", TaskStatus.failed, error="mock data rejected")

    fresh = original.model_copy(deep=True)
    fresh.id = "r-new"
    fresh.status = RunStatus.pending
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    reloaded = store.load_run("r-new")
    by_id = {t.id: t for t in reloaded.tasks}
    assert reloaded.status == RunStatus.completed
    assert by_id["t-x"].summary == "KEPT-X"
    assert by_id["t-y"].status == TaskStatus.completed
    assert by_id["t-y"].summary == "KEPT-LAYER2", "completed later-layer task must be kept"
    assert by_id["t-z"].summary == "fresh-t-z"
    t_z_upstream = dict(workers_succeed.calls[-1][1])
    assert t_z_upstream.get("y") == "KEPT-LAYER2"
    # Only t-z ran; t-x and t-y were never dispatched.
    assert [tid for tid, _ in workers_succeed.calls] == ["t-z"]


def test_replay_rejects_dotdot_artifact_clobber(tmp_path, workers_succeed):
    """artifacts/../run.json normalizes into the run root and must be dropped —
    it would otherwise overwrite the new run's control file."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", RunStatus.failed)
    store.create_run(original)
    task_store = TaskStore(store.run_dir(original.id))
    for task in original.tasks:
        task_store.save_task(task)
    task_store.update_status(
        "t-a",
        TaskStatus.completed,
        summary="KEPT",
        completed_at="2026-08-20T09:01:00+00:00",
        artifacts=["artifacts/../run.json"],
    )
    task_store.update_status("t-b", TaskStatus.failed, error="mock data rejected")
    task_store.update_status("t-c", TaskStatus.blocked, error="upstream failed")

    fresh = _make_dag_run("r-new", RunStatus.pending)
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    by_id = {t.id: t for t in store.load_run("r-new").tasks}
    assert by_id["t-a"].artifacts == [], (
        "dotdot artifact path must be dropped, not clobber the run's control file"
    )
    reloaded = store.load_run("r-new")
    assert reloaded.id == "r-new", "new run's control file must not be overwritten"
    assert reloaded.status == RunStatus.completed


def test_replay_source_symlink_artifact_dropped(tmp_path, workers_succeed):
    """A symlinked component in the SOURCE artifact tree (artifacts/analyst ->
    tasks) must not redirect a re-homed artifact onto task files."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", RunStatus.failed)
    store.create_run(original)
    task_store = TaskStore(store.run_dir(original.id))
    for task in original.tasks:
        task_store.save_task(task)
    task_store.update_status(
        "t-a",
        TaskStatus.completed,
        summary="KEPT",
        completed_at="2026-08-20T09:01:00+00:00",
        artifacts=["artifacts/analyst/task-t-a.json"],
    )
    task_store.update_status("t-b", TaskStatus.failed, error="mock data rejected")
    task_store.update_status("t-c", TaskStatus.blocked, error="upstream failed")
    # Plant an internal symlink: artifacts/analyst -> tasks.
    run_dir = store.run_dir(original.id)
    analyst = run_dir / "artifacts" / "analyst"
    analyst.parent.mkdir(parents=True, exist_ok=True)
    analyst.symlink_to(run_dir / "tasks", target_is_directory=True)

    fresh = _make_dag_run("r-new", RunStatus.pending)
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    by_id = {t.id: t for t in store.load_run("r-new").tasks}
    assert by_id["t-a"].artifacts == [], (
        "artifact resolving outside the source artifacts subtree must be dropped"
    )
    assert {t.id for t in store.load_run("r-new").tasks} == {"t-a", "t-b", "t-c"}, (
        "new run's task files must remain intact"
    )


def test_replay_does_not_keep_changed_agent_definition(tmp_path, workers_succeed):
    """A completed task must not be kept when the agent that executes it changed
    (here its system prompt) even though the task fields are identical."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", RunStatus.failed)
    _seed_original_run(store, original)

    fresh = _make_dag_run("r-new", RunStatus.pending)
    for agent in fresh.agents:
        if agent.id == "analyst":
            agent.system_prompt = "a completely different analyst"
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    by_id = {t.id: t for t in store.load_run("r-new").tasks}
    assert by_id["t-a"].status == TaskStatus.completed
    assert by_id["t-a"].summary == "fresh-t-a", (
        "changed agent definition must re-execute, not keep the old result"
    )
    assert [tid for tid, _ in workers_succeed.calls] == ["t-a", "t-b", "t-c"]


def test_replay_reexecutes_dependents_of_reexecuted_upstream(tmp_path, workers_succeed):
    """When a kept-candidate's upstream re-executes (definition changed), the
    dependent must also re-execute — its kept summary would be stale relative
    to the fresh upstream output flowing into it."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    agents = [
        SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="x", max_retries=0),
        SwarmAgentSpec(id="pm", role="PM", system_prompt="x", max_retries=0),
    ]
    original = SwarmRun(
        id="r-orig",
        preset_name="demo",
        created_at="2026-08-20T09:00:00+00:00",
        agents=agents,
        tasks=[
            SwarmTask(id="t-x", agent_id="analyst", prompt_template="do x"),
            SwarmTask(
                id="t-y",
                agent_id="pm",
                prompt_template="do y",
                depends_on=["t-x"],
                blocked_by=["t-x"],
                input_from={"x": "t-x"},
            ),
            SwarmTask(
                id="t-z",
                agent_id="pm",
                prompt_template="do z",
                depends_on=["t-y"],
                blocked_by=["t-y"],
                input_from={"y": "t-y"},
            ),
        ],
    )
    original.status = RunStatus.failed
    store.create_run(original)
    task_store = TaskStore(store.run_dir(original.id))
    for task in original.tasks:
        task_store.save_task(task)
    task_store.update_status(
        "t-x", TaskStatus.completed, summary="OLD-X",
        completed_at="2026-08-20T09:01:00+00:00", artifacts=[],
    )
    task_store.update_status(
        "t-y", TaskStatus.completed, summary="OLD-Y",
        completed_at="2026-08-20T09:02:00+00:00", artifacts=[],
    )
    task_store.update_status("t-z", TaskStatus.failed, error="mock data rejected")

    fresh = original.model_copy(deep=True)
    fresh.id = "r-new"
    fresh.status = RunStatus.pending
    for task in fresh.tasks:
        if task.id == "t-x":
            task.prompt_template = "do x, but differently"
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    reloaded = store.load_run("r-new")
    by_id = {t.id: t for t in reloaded.tasks}
    assert reloaded.status == RunStatus.completed
    assert by_id["t-x"].summary == "fresh-t-x", "changed upstream must re-execute"
    assert by_id["t-y"].summary == "fresh-t-y", (
        "dependent of a re-executed upstream must re-execute, not keep a stale summary"
    )
    assert by_id["t-z"].summary == "fresh-t-z"
    assert [tid for tid, _ in workers_succeed.calls] == ["t-x", "t-y", "t-z"]


def test_replay_destination_artifacts_dir_symlink_escape_blocked(tmp_path, workers_succeed):
    """A symlink replacing the NEW run's whole artifacts/ dir must not let a
    re-homed artifact write outside the run — the containment check is against
    both the run root and the artifacts subtree, so the symlink cannot redefine
    the safe boundary."""
    outside = tmp_path / "outside"
    outside.mkdir()
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", RunStatus.failed)
    _seed_original_run(store, original)

    fresh = _make_dag_run("r-new", RunStatus.pending)
    store.create_run(fresh)
    # Replace the new run's real artifacts/ dir with a symlink to an external
    # dir (as a tampering process with run-dir access could before the overlay).
    artifacts_rd = store.run_dir("r-new") / "artifacts"
    artifacts_rd.rmdir()
    artifacts_rd.symlink_to(outside, target_is_directory=True)

    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    by_id = {t.id: t for t in store.load_run("r-new").tasks}
    assert by_id["t-a"].artifacts == [], (
        "artifact re-home must refuse a destination outside the run dir"
    )
    assert list(outside.iterdir()) == [], "nothing may be written outside the run dir"


def test_replay_does_not_keep_run_level_model_change(tmp_path, workers_succeed):
    """A global model/provider swap between runs must invalidate kept results
    when agents use the run-level default (model_name=None) — the effective
    model that produced a kept result must still mean the same thing."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", RunStatus.failed)
    original.model = "deepseek-v1"
    original.provider = "openai"
    _seed_original_run(store, original)

    fresh = _make_dag_run("r-new", RunStatus.pending)
    fresh.model = "deepseek-v2"  # global default changed; agents unchanged
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    by_id = {t.id: t for t in store.load_run("r-new").tasks}
    assert by_id["t-a"].status == TaskStatus.completed
    assert by_id["t-a"].summary == "fresh-t-a", (
        "run-level model change must invalidate kept results produced under the old default"
    )
    calls = workers_succeed.calls
    assert sorted(tid for tid, _ in calls[:-1]) == ["t-a", "t-b"]
    assert calls[-1] == ("t-c", {"a": "fresh-t-a", "b": "fresh-t-b"})


def test_replay_seeds_none_summary_key_for_downstream(tmp_path, workers_succeed):
    """A kept task whose stored summary is None must still contribute its
    input_from key to re-executed dependents — the live run path seeds the key
    unconditionally, so a silent None must not behave differently."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    agents = [
        SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="x", max_retries=0),
        SwarmAgentSpec(id="pm", role="PM", system_prompt="x", max_retries=0),
    ]
    original = SwarmRun(
        id="r-orig",
        preset_name="demo",
        created_at="2026-08-20T09:00:00+00:00",
        agents=agents,
        tasks=[
            SwarmTask(id="t-a", agent_id="analyst", prompt_template="do a"),
            SwarmTask(
                id="t-b",
                agent_id="pm",
                prompt_template="do b",
                depends_on=["t-a"],
                blocked_by=["t-a"],
                input_from={"a": "t-a"},
            ),
        ],
    )
    original.status = RunStatus.failed
    store.create_run(original)
    task_store = TaskStore(store.run_dir(original.id))
    for task in original.tasks:
        task_store.save_task(task)
    # t-a completed but its stored summary is None (legacy/corrupt old state).
    task_store.update_status(
        "t-a",
        TaskStatus.completed,
        summary=None,
        completed_at="2026-08-20T09:01:00+00:00",
        artifacts=[],
    )
    task_store.update_status("t-b", TaskStatus.failed, error="mock data rejected")

    fresh = original.model_copy(deep=True)
    fresh.id = "r-new"
    fresh.status = RunStatus.pending
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    reloaded = store.load_run("r-new")
    by_id = {t.id: t for t in reloaded.tasks}
    assert reloaded.status == RunStatus.completed
    assert by_id["t-a"].summary is None, "kept task keeps its (None) summary"
    assert by_id["t-b"].status == TaskStatus.completed
    t_b_upstream = dict(workers_succeed.calls[-1][1])
    assert "a" in t_b_upstream, (
        "None-summary kept task must still contribute its input_from key"
    )


def test_replay_partially_missing_store_keeps_present_completed(tmp_path, workers_succeed):
    """A task file missing from an otherwise-readable store does not trigger the
    fresh-run fallback: present completed tasks are kept, missing ones re-execute
    (documented partial-resume contract, distinct from whole-store degradation)."""
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    original = _make_dag_run("r-orig", RunStatus.failed)
    _seed_original_run(store, original)
    # Delete t-b's task file: it exists in the run model but not the store.
    (store.run_dir("r-orig") / "tasks" / "task-t-b.json").unlink()

    fresh = _make_dag_run("r-new", RunStatus.pending)
    store.create_run(fresh)
    runtime._execute_run(fresh, threading.Event(), resume_from=original)

    reloaded = store.load_run("r-new")
    by_id = {t.id: t for t in reloaded.tasks}
    assert reloaded.status == RunStatus.completed
    assert by_id["t-a"].summary == "AAPL BUY 5 conviction", (
        "present completed task with a readable file must still be kept"
    )
    assert by_id["t-b"].summary == "fresh-t-b", "missing task file must re-execute"
