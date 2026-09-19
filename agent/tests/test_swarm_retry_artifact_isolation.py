"""Regression tests: a retried worker attempt must not inherit stale
artifacts (report.md, or any other tool-written file) from a prior failed
attempt for the same task.

``_run_worker_with_retries`` re-invokes ``run_worker`` against the *same*
``artifact_dir`` on every attempt (``mkdir(parents=True, exist_ok=True)``,
no cleanup). ``_resolve_summary``/``_report_written``/``_collect_artifacts``
all read whatever is currently sitting in that directory, with no way to
tell which attempt wrote it. Without isolation, a worker that fails after
writing report.md, followed by a retry that fails immediately (a realistic
sequence of two ordinary transient LLM/provider errors), silently returns
the discarded first attempt's stale content as the retried attempt's real
result.

The real ``_resolve_summary``/``_report_written``/``_collect_artifacts``
are exercised for real inside the mocked ``run_worker`` below (only the
expensive LLM/tool-loop internals are mocked out), so these tests prove the
actual interaction between the retry loop's cleanup and worker.py's
artifact-reading functions, not just one function in isolation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.swarm.models import SwarmAgentSpec, SwarmTask, WorkerResult
from src.swarm.runtime import SwarmRuntime
from src.swarm.store import SwarmStore
from src.swarm.worker import (
    _collect_artifacts,
    _resolve_summary,
    agent_artifact_dir,
    clear_agent_artifacts,
)


def _make_runtime(tmp_path: Path) -> SwarmRuntime:
    store = SwarmStore(base_dir=tmp_path / "swarm_runs")
    return SwarmRuntime(store=store)


def _make_agent_spec(max_retries: int) -> SwarmAgentSpec:
    return SwarmAgentSpec(
        id="analyst",
        role="Analyst",
        system_prompt="x",
        tools=["read_file"],
        skills=[],
        max_iterations=1,
        timeout_seconds=5,
        max_retries=max_retries,
    )


def _make_task() -> SwarmTask:
    return SwarmTask(id="task-1", agent_id="analyst", prompt_template="do x")


# --------------------------------------------------------------------------- #
# Unit tests: the two new helpers themselves
# --------------------------------------------------------------------------- #


def test_agent_artifact_dir_matches_run_worker_construction(tmp_path: Path) -> None:
    """The shared helper must resolve to the exact path run_worker() writes
    to, or the retry loop would clear the wrong directory entirely."""
    run_dir = tmp_path / "run-x"
    assert agent_artifact_dir(run_dir, "analyst") == run_dir / "artifacts" / "analyst"


@pytest.mark.parametrize(
    "agent_id", ["..", "/abs/path", "", ".", "a/b", r"a\\b"]
)
def test_agent_artifact_dir_rejects_path_shaped_ids(
    tmp_path: Path, agent_id: str
) -> None:
    with pytest.raises(ValueError, match="agent id"):
        agent_artifact_dir(tmp_path / "run-x", agent_id)


def test_agent_artifact_dir_rejects_canonical_symlink_escape(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-x"
    artifact_root = run_dir / "artifacts"
    artifact_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (artifact_root / "analyst").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="agent id"):
        agent_artifact_dir(run_dir, "analyst")


def test_clear_agent_artifacts_removes_nested_files_and_dirs(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts" / "analyst"
    (artifact_dir / "charts").mkdir(parents=True)
    (artifact_dir / "report.md").write_text("stale", encoding="utf-8")
    (artifact_dir / "charts" / "plot.png").write_text("stale-binary", encoding="utf-8")

    clear_agent_artifacts(artifact_dir)

    assert not artifact_dir.exists()


def test_clear_agent_artifacts_is_noop_when_directory_absent(tmp_path: Path) -> None:
    """Nothing to clean up before the very first attempt — must not raise."""
    artifact_dir = tmp_path / "artifacts" / "analyst"
    assert not artifact_dir.exists()
    clear_agent_artifacts(artifact_dir)  # must not raise
    assert not artifact_dir.exists()


# --------------------------------------------------------------------------- #
# Integration: the real retry loop + the real artifact-reading functions
# --------------------------------------------------------------------------- #


def test_stale_report_not_returned_after_retry(tmp_path: Path) -> None:
    """Attempt 1 writes report.md then fails; attempt 2 fails before writing
    anything. Attempt 1's report must not become attempt 2's result."""
    runtime = _make_runtime(tmp_path)
    agent_spec = _make_agent_spec(max_retries=1)
    task = _make_task()
    run_dir = tmp_path / "run-stale-report"
    run_dir.mkdir()
    artifact_dir = agent_artifact_dir(run_dir, "analyst")

    calls = {"n": 0}

    def fake_run_worker(**kwargs):
        calls["n"] += 1
        artifact_dir.mkdir(parents=True, exist_ok=True)
        if calls["n"] == 1:
            (artifact_dir / "report.md").write_text(
                "# Attempt 1 (discarded)\nSHORT thesis on stale data.",
                encoding="utf-8",
            )
            return WorkerResult(
                status="failed",
                summary=_resolve_summary(artifact_dir, "attempt 1 raw fallback"),
                error="attempt 1: provider error",
            )
        # Attempt 2 fails immediately — no report.md written this attempt.
        return WorkerResult(
            status="failed",
            summary=_resolve_summary(artifact_dir, "attempt 2 real fallback"),
            error="attempt 2: provider error",
        )

    with patch("src.swarm.runtime.run_worker", side_effect=fake_run_worker):
        result = runtime._run_worker_with_retries(
            agent_spec=agent_spec,
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=run_dir,
            event_callback=None,
            run_id="run-stale-report",
            include_shell_tools=False,
            grounding_block="",
        )

    assert calls["n"] == 2
    assert result.summary == "attempt 2 real fallback"
    assert "Attempt 1" not in result.summary
    assert not (artifact_dir / "report.md").exists()


def test_stale_non_report_artifact_not_leaked_after_retry(tmp_path: Path) -> None:
    """Attempt 1 writes a non-report file (e.g. a chart/CSV a tool
    produced) then fails; attempt 2 writes nothing and fails too. The final
    artifact_paths must not contain attempt 1's file — proves the fix
    clears the whole directory, not just report.md."""
    runtime = _make_runtime(tmp_path)
    agent_spec = _make_agent_spec(max_retries=1)
    task = _make_task()
    run_dir = tmp_path / "run-stale-artifact"
    run_dir.mkdir()
    artifact_dir = agent_artifact_dir(run_dir, "analyst")

    calls = {"n": 0}

    def fake_run_worker(**kwargs):
        calls["n"] += 1
        artifact_dir.mkdir(parents=True, exist_ok=True)
        if calls["n"] == 1:
            (artifact_dir / "analysis.csv").write_text(
                "date,close\n2026-01-01,100\n", encoding="utf-8"
            )
            return WorkerResult(
                status="failed",
                summary="attempt 1 raw fallback",
                artifact_paths=_collect_artifacts(artifact_dir),
                error="attempt 1: tool error",
            )
        return WorkerResult(
            status="failed",
            summary="attempt 2 real fallback",
            artifact_paths=_collect_artifacts(artifact_dir),
            error="attempt 2: provider error",
        )

    with patch("src.swarm.runtime.run_worker", side_effect=fake_run_worker):
        result = runtime._run_worker_with_retries(
            agent_spec=agent_spec,
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=run_dir,
            event_callback=None,
            run_id="run-stale-artifact",
            include_shell_tools=False,
            grounding_block="",
        )

    assert calls["n"] == 2
    assert result.artifact_paths == []
    assert not (artifact_dir / "analysis.csv").exists()


def test_successful_retry_only_reflects_current_attempt_artifacts(
    tmp_path: Path,
) -> None:
    """Control: attempt 1 fails with artifacts on disk; attempt 2 succeeds
    with its own, different report/artifact. Only attempt 2's content and
    files must be returned — failed-attempt artifacts disappear,
    successful-attempt artifacts remain."""
    runtime = _make_runtime(tmp_path)
    agent_spec = _make_agent_spec(max_retries=1)
    task = _make_task()
    run_dir = tmp_path / "run-successful-retry"
    run_dir.mkdir()
    artifact_dir = agent_artifact_dir(run_dir, "analyst")

    calls = {"n": 0}

    def fake_run_worker(**kwargs):
        calls["n"] += 1
        artifact_dir.mkdir(parents=True, exist_ok=True)
        if calls["n"] == 1:
            (artifact_dir / "report.md").write_text(
                "Attempt 1 (discarded)", encoding="utf-8"
            )
            (artifact_dir / "chart.png").write_text(
                "stale-chart-bytes", encoding="utf-8"
            )
            return WorkerResult(
                status="failed",
                summary=_resolve_summary(artifact_dir, "attempt 1 raw fallback"),
                artifact_paths=_collect_artifacts(artifact_dir),
                error="attempt 1: provider error",
            )
        (artifact_dir / "report.md").write_text(
            "# Attempt 2 (real result)\nLONG thesis.", encoding="utf-8"
        )
        return WorkerResult(
            status="completed",
            summary=_resolve_summary(artifact_dir, "attempt 2 raw fallback"),
            artifact_paths=_collect_artifacts(artifact_dir),
        )

    with patch("src.swarm.runtime.run_worker", side_effect=fake_run_worker):
        result = runtime._run_worker_with_retries(
            agent_spec=agent_spec,
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=run_dir,
            event_callback=None,
            run_id="run-successful-retry",
            include_shell_tools=False,
            grounding_block="",
        )

    assert calls["n"] == 2
    assert result.status == "completed"
    assert "Attempt 2" in result.summary
    assert "Attempt 1" not in result.summary
    assert result.artifact_paths == ["artifacts/analyst/report.md"]


def test_stale_report_not_leaked_from_earlier_task_sharing_the_same_agent(
    tmp_path: Path,
) -> None:
    """agent_artifact_dir is keyed by agent_id alone, so a preset where one
    agent handles two sequential tasks (task-2 depends_on task-1) reuses the
    same directory. task-1's report.md must not survive to be read back as
    task-2's result."""
    runtime = _make_runtime(tmp_path)
    agent_spec = _make_agent_spec(max_retries=0)
    run_dir = tmp_path / "run-shared-agent"
    run_dir.mkdir()
    artifact_dir = agent_artifact_dir(run_dir, "analyst")

    def fake_run_worker(**kwargs):
        artifact_dir.mkdir(parents=True, exist_ok=True)
        task = kwargs["task"]
        if task.id == "task-1":
            (artifact_dir / "report.md").write_text(
                "# Task 1 report\nTASK-1 CONTENT.", encoding="utf-8"
            )
        return WorkerResult(
            status="completed",
            summary=_resolve_summary(artifact_dir, f"{task.id} raw fallback"),
            artifact_paths=_collect_artifacts(artifact_dir),
        )

    task1 = SwarmTask(id="task-1", agent_id="analyst", prompt_template="do x")
    task2 = SwarmTask(id="task-2", agent_id="analyst", prompt_template="do y")

    with patch("src.swarm.runtime.run_worker", side_effect=fake_run_worker):
        result1 = runtime._run_worker_with_retries(
            agent_spec=agent_spec,
            task=task1,
            upstream_summaries={},
            user_vars={},
            run_dir=run_dir,
            event_callback=None,
            run_id="run-shared-agent",
            include_shell_tools=False,
            grounding_block="",
        )
        result2 = runtime._run_worker_with_retries(
            agent_spec=agent_spec,
            task=task2,
            upstream_summaries={},
            user_vars={},
            run_dir=run_dir,
            event_callback=None,
            run_id="run-shared-agent",
            include_shell_tools=False,
            grounding_block="",
        )

    assert "Task 1 report" in result1.summary
    assert result2.summary == "task-2 raw fallback"
    assert "Task 1" not in result2.summary
    assert result2.artifact_paths == []
