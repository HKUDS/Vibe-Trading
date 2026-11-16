"""Continue saved research without replaying tools or hiding partial delivery."""

from __future__ import annotations

import json
import threading

from src.providers.chat import LLMResponse, ToolCallRequest
from src.swarm import checkpoint
from src.swarm.models import SwarmAgentSpec, SwarmTask
from src.swarm.worker import _run_worker_impl, agent_artifact_dir


class Registry:
    def __init__(self):
        self.calls = 0

    def get_definitions(self):
        return []

    def get(self, name):
        return None

    def execute(self, name, arguments):
        self.calls += 1
        return json.dumps({"status": "ok", "revenue_usd": 26000000000})


class Provider:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.seen = []

    def stream_chat(self, messages, **kwargs):
        self.seen.append(json.loads(json.dumps(messages)))
        step = next(self.steps)
        if callable(step):
            return step(kwargs)
        return step


def run(tmp_path, registry, monkeypatch, provider, **kwargs):
    monkeypatch.setattr("src.swarm.worker.build_swarm_registry", lambda *a, **k: registry)
    return _run_worker_impl(
        SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="Research", max_iterations=4),
        SwarmTask(id="task", agent_id="analyst", prompt_template="Analyze NVDA"),
        {},
        {},
        tmp_path,
        llm=provider,
        **kwargs,
    )


def fail_stream(kwargs):
    kwargs["on_text_chunk"]("Revenue $26B; remaining risk work")
    raise RuntimeError("provider disconnected")


def test_retry_preserves_real_tool_result_and_partial_stream(tmp_path, monkeypatch):
    registry = Registry()
    first = Provider(
        [
            LLMResponse(
                content="Reading filing",
                tool_calls=[ToolCallRequest(id="filing", name="probe", arguments={})],
                finish_reason="tool_calls",
            ),
            fail_stream,
        ]
    )
    interrupted = run(tmp_path, registry, monkeypatch, first)
    assert interrupted.status == "failed"
    assert interrupted.summary == "Revenue $26B; remaining risk work"
    assert registry.calls == 1
    artifact = agent_artifact_dir(tmp_path, "analyst", "task")
    assert (artifact / "messages.json").is_file()
    # Old tool-written deliverables must not replace the resumed conclusion.
    (artifact / "report.md").write_text("Old preliminary view")
    second = Provider([LLMResponse(content="Hold. Revenue $26B; risk still uncertain.", finish_reason="stop")])
    completed = run(tmp_path, registry, monkeypatch, second, resume=True)
    assert completed.status == "completed"
    assert completed.summary == "Hold. Revenue $26B; risk still uncertain."
    assert registry.calls == 1
    messages = second.seen[0]
    assert any(m.get("role") == "tool" and "26000000000" in m["content"] for m in messages)
    assert any(m.get("content") == interrupted.summary for m in messages)
    assert messages[-1]["role"] == "user"


def test_cancelled_stream_is_saved_without_dispatching_tools(tmp_path, monkeypatch):
    registry = Registry()
    cancel = threading.Event()

    def cancelled(kwargs):
        kwargs["on_text_chunk"]("Available evidence: $26B")
        cancel.set()
        return LLMResponse(
            content="Available evidence: $26B", tool_calls=[ToolCallRequest(id="never", name="probe", arguments={})]
        )

    result = run(tmp_path, registry, monkeypatch, Provider([cancelled]), cancel_event=cancel)
    assert result.status == "cancelled"
    assert result.summary == "Available evidence: $26B"
    assert registry.calls == 0
    data = json.loads((agent_artifact_dir(tmp_path, "analyst", "task") / checkpoint.FILENAME).read_text())
    assert data["last_content"] == result.summary


def test_unknown_tool_outcome_is_disclosed_not_replayed(tmp_path):
    initial = [
        {"role": "system", "content": "research\n## Current Date & Time\nold"},
        {"role": "user", "content": "task"},
    ]
    key = checkpoint.context_key(initial)
    messages = initial + [
        {
            "role": "assistant",
            "content": "Saving report",
            "tool_calls": [{"id": "pending", "function": {"name": "write_file", "arguments": "{}"}}],
        }
    ]
    checkpoint.save(tmp_path, key=key, messages=messages, last_content="Saving report", run_dir=tmp_path)
    fresh = {"role": "system", "content": "research\n## Current Date & Time\nnew"}
    restored, _ = checkpoint.restore(tmp_path, key=key, system=fresh, run_dir=tmp_path / "next")
    assert restored[0] == fresh
    outcomes = [m for m in restored if m.get("tool_call_id") == "pending"]
    assert len(outcomes) == 1
    assert json.loads(outcomes[0]["content"])["error_code"] == "interrupted_tool_result"
    assert checkpoint.restore(tmp_path, key="different instructions", system=fresh, run_dir=tmp_path) is None


def test_empty_resumed_response_does_not_pass_using_old_report(tmp_path, monkeypatch):
    registry = Registry()
    run(tmp_path, registry, monkeypatch, Provider([fail_stream]))
    artifact = agent_artifact_dir(tmp_path, "analyst", "task")
    (artifact / "report.md").write_text("Prior partial analysis")
    result = run(
        tmp_path, registry, monkeypatch, Provider([LLMResponse(content="", finish_reason="stop")]), resume=True
    )
    assert result.status == "incomplete"
    assert result.error == "empty response"
    assert result.summary == "Prior partial analysis"


def test_explicit_continuation_copies_checkpoint_and_keeps_completed_input(tmp_path):
    from src.swarm.models import RunStatus, SwarmRun, TaskStatus
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore
    from src.swarm.task_store import TaskStore

    store = SwarmStore(base_dir=tmp_path)
    agents = [SwarmAgentSpec(id=x, role=x, system_prompt="research") for x in ("a", "b")]
    tasks = [
        SwarmTask(id="a", agent_id="a", prompt_template="research"),
        SwarmTask(id="b", agent_id="b", prompt_template="synthesize", depends_on=["a"], input_from={"input": "a"}),
    ]
    prior = SwarmRun(
        id="old",
        preset_name="demo",
        agents=agents,
        tasks=tasks,
        user_vars={"target": "NVDA"},
        created_at="2026-11-13T00:00:00Z",
        status=RunStatus.failed,
    )
    store.create_run(prior)
    previous = TaskStore(store.run_dir(prior.id))
    for task in tasks:
        previous.save_task(task)
    previous.update_status("a", TaskStatus.completed, summary="Revenue $26B")
    previous.update_status("b", TaskStatus.failed, summary="Risk work in progress")
    artifact = agent_artifact_dir(store.run_dir(prior.id), "b", "b")
    artifact.mkdir(parents=True)
    (artifact / checkpoint.FILENAME).write_text('{"version": 1, "messages": []}')
    (artifact / "report.md").write_text("Prior partial work")
    resumed = prior.model_copy(update={"id": "next", "status": RunStatus.pending})
    store.create_run(resumed)
    current = TaskStore(store.run_dir(resumed.id))
    for task in tasks:
        current.save_task(task)
    summaries = {}
    SwarmRuntime(store)._apply_resume_overlay(resumed, store.run_dir(resumed.id), current, prior, summaries)
    assert summaries == {"a": "Revenue $26B"}
    assert current.load_task("b").status == TaskStatus.pending
    copied = agent_artifact_dir(store.run_dir(resumed.id), "b", "b")
    assert (copied / checkpoint.FILENAME).read_bytes() == (artifact / checkpoint.FILENAME).read_bytes()
    assert (copied / "report.md").read_text() == "Prior partial work"
    # Different questions must not inherit prior securities' completed research.
    changed = resumed.model_copy(update={"id": "different", "user_vars": {"target": "JPM"}})
    store.create_run(changed)
    current = TaskStore(store.run_dir(changed.id))
    for task in tasks:
        current.save_task(task)
    kept = {}
    SwarmRuntime(store)._apply_resume_overlay(changed, store.run_dir(changed.id), current, prior, kept)
    assert not kept
    assert not (agent_artifact_dir(store.run_dir(changed.id), "b", "b") / checkpoint.FILENAME).exists()


def test_agent_tool_resumes_original_run_without_rerouting(tmp_path, monkeypatch):
    from src.swarm.models import RunStatus, SwarmRun, TaskStatus
    from src.swarm.store import SwarmStore
    from src.swarm.task_store import TaskStore
    from src.tools.swarm_tool import SwarmTool

    monkeypatch.setattr("src.swarm.store.swarm_runs_root", lambda: tmp_path)
    monkeypatch.setattr("src.config.load_swarm_agent_config", lambda: None)
    store = SwarmStore(base_dir=tmp_path)
    task = SwarmTask(
        id="done",
        agent_id="analyst",
        prompt_template="Analyze NVDA",
        status=TaskStatus.completed,
        summary="Retained research",
    )
    prior = SwarmRun(
        id="original",
        preset_name="investment_committee",
        status=RunStatus.failed,
        user_vars={"target": "NVDA", "market": "US"},
        tasks=[task],
        created_at="2026-11-13T00:00:00Z",
    )
    store.create_run(prior)
    TaskStore(store.run_dir(prior.id)).save_task(task)
    calls = []

    def start(runtime, preset, variables, **kwargs):
        calls.append((preset, variables, kwargs["resume_from"].id))
        next_run = prior.model_copy(update={"id": "resumed", "status": RunStatus.completed, "final_report": "Hold."})
        store.create_run(next_run)
        TaskStore(store.run_dir(next_run.id)).save_task(task)
        return next_run

    monkeypatch.setattr("src.swarm.runtime.SwarmRuntime.start_run", start)
    result = json.loads(SwarmTool().execute(prompt="Continue the unfinished work", resume_run_id=prior.id))
    assert calls == [("investment_committee", {"target": "NVDA", "market": "US"}, "original")]
    assert result["run_id"] == "resumed"
    assert result["final_report"] == "Hold."
    assert result["report_is_partial"] is False


def test_fresh_final_response_supersedes_earlier_report_file(tmp_path, monkeypatch):
    class ReportRegistry(Registry):
        def execute(self, name, arguments):
            artifact = agent_artifact_dir(tmp_path, "analyst", "task")
            (artifact / "report.md").write_text("Preliminary: risk sample is short.")
            return '{"status":"ok"}'
    final = "Final: 508 returns, 26 tail observations. Financials are inherited, not newly fetched."
    provider = Provider([
        LLMResponse(content="", tool_calls=[ToolCallRequest(id="draft", name="write_file", arguments={})], finish_reason="tool_calls"),
        LLMResponse(content=final, finish_reason="stop"),
    ])
    result = run(tmp_path, ReportRegistry(), monkeypatch, provider)
    assert result.status == "completed"
    assert result.summary == final
    artifact = agent_artifact_dir(tmp_path, "analyst", "task")
    assert (artifact / "report.md").read_text() == "Preliminary: risk sample is short."
    assert json.loads((artifact / "messages.json").read_text())[-1]["content"] == final
