"""Real runtime and workers write distinct same-agent task reports and logs."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

import src.swarm.worker as worker
from src.providers.chat import LLMResponse, ToolCallRequest
from src.swarm.models import RunStatus, SwarmAgentSpec, SwarmRun, SwarmTask, TaskStatus
from src.swarm.runtime import SwarmRuntime
from src.swarm.store import SwarmStore


@pytest.mark.parametrize("parallel", [False, True])
def test_runtime_preserves_each_same_agent_tasks_real_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parallel: bool
) -> None:
    barrier = threading.Barrier(2) if parallel else None
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))

    class ReportLLM:
        def __init__(self, **kwargs):
            self.wrote = False

        def stream_chat(self, messages, **kwargs):
            task_id = messages[1]["content"]
            report = (
                f"# {task_id}\nThe requested research is complete. "
                "This task produced its own report and a clear conclusion, "
                "with the evidence and limitations recorded for the reader."
            )
            if not self.wrote:
                if barrier is not None:
                    barrier.wait(timeout=10)
                self.wrote = True
                return LLMResponse(tool_calls=[ToolCallRequest(
                    id=f"write-{task_id}", name="write_file",
                    arguments={"path": "report.md", "content": report},
                )], finish_reason="tool_calls")
            result = json.loads(next(message["content"] for message in messages if message["role"] == "tool"))
            assert result["status"] == "ok", result
            return LLMResponse(content=report, tool_calls=[], finish_reason="stop")

        def close(self):
            pass

    monkeypatch.setattr(worker, "ChatLLM", ReportLLM)
    store = SwarmStore(base_dir=tmp_path)
    agent = SwarmAgentSpec(
        id="analyst", role="Report writer", system_prompt="Write the task report.",
        tools=["write_file"], max_iterations=3, max_retries=0,
    )
    tasks = [
        SwarmTask(id="first", agent_id=agent.id, prompt_template="first"),
        SwarmTask(
            id="second", agent_id=agent.id, prompt_template="second",
            depends_on=[] if parallel else ["first"],
        ),
    ]
    run = SwarmRun(
        id="task-isolation", preset_name="fixture", created_at="2026-10-03T00:00:00Z",
        agents=[agent], tasks=tasks,
    )
    store.create_run(run)
    runtime = SwarmRuntime(store=store)
    runtime._execute_run(run, threading.Event())
    saved = store.load_run(run.id)
    assert saved is not None and saved.status == RunStatus.completed
    for task in saved.tasks:
        assert task.status == TaskStatus.completed, task.error
        assert task.summary.startswith(f"# {task.id}\n")
        directory = store.run_dir(run.id) / "artifacts" / agent.id / task.id
        assert (directory / "report.md").read_text() == task.summary
        assert (directory / "summary.md").read_text() == task.summary
        messages = json.loads((directory / "messages.json").read_text())
        assert messages[1]["content"] == task.id
        assert all(path.startswith(f"artifacts/{agent.id}/{task.id}/") for path in task.artifacts)


def test_internal_task_symlink_cannot_share_a_siblings_directory(tmp_path: Path) -> None:
    parent = tmp_path / "artifacts" / "analyst"
    (parent / "second").mkdir(parents=True)
    (parent / "first").symlink_to(parent / "second", target_is_directory=True)
    with pytest.raises(ValueError):
        worker.agent_artifact_dir(tmp_path, "analyst", "first")
