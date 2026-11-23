"""Continue saved research without replaying tools or hiding partial delivery."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import json
import threading

from src.kernel.contracts import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmTask
from src.session.thread import ThreadLog
from src.swarm.artifacts import agent_artifact_dir, node_thread
from src.swarm.node import UNKNOWN_TOOL_OUTCOME, run_node


class Registry:
    def __init__(self):
        self.calls = 0
        self.policy = ToolPolicy.from_config(get_env_config())

    def get_definitions(self):
        return []

    def get(self, name):
        return None

    def execute(self, name, arguments):
        self.calls += 1
        return json.dumps({"status": "ok", "revenue_usd": 26000000000})

    def check_policy(self, name, arguments):
        return self.policy(name, arguments)


class Provider:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.seen = []

    def close(self):
        pass

    def stream_chat(self, messages, **kwargs):
        self.seen.append(json.loads(json.dumps(messages)))
        step = next(self.steps)
        if callable(step):
            return step(kwargs)
        return step


def run(tmp_path, registry, monkeypatch, provider, **kwargs):
    monkeypatch.setattr("src.swarm.node.build_swarm_registry", lambda *a, **k: registry)
    monkeypatch.setattr("src.swarm.node.ChatLLM", lambda **kwargs: provider)
    return run_node(
        SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="Research", max_iterations=4),
        SwarmTask(id="task", agent_id="analyst", prompt_template="Analyze NVDA"),
        {},
        {},
        tmp_path,
        **kwargs,
        policy=ToolPolicy.from_config(get_env_config()),
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
    assert node_thread(tmp_path, "analyst", "task").is_file()
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
    items = ThreadLog(node_thread(tmp_path, "analyst", "task")).read()
    assert any(item.type == "assistant" and item.get("content") == result.summary for item in items)


def test_unknown_tool_outcome_is_disclosed_not_replayed(tmp_path, monkeypatch):
    path = node_thread(tmp_path, "analyst", "task")
    ThreadLog(path).append(
        "assistant", "interrupted", phase="commentary", content="Saving report",
        tool_calls=[{"id": "pending", "type": "function", "function": {"name": "write_file", "arguments": "{}"}}],
    )
    registry = Registry()
    model = Provider([])
    result = run(tmp_path, registry, monkeypatch, model, resume=True)
    assert result.error == UNKNOWN_TOOL_OUTCOME
    assert not model.seen
    assert registry.calls == 0


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
    previous.update_status("b", TaskStatus.failed, summary="Risk work in progress",
                           artifacts=["artifacts/b/b/report.md"])
    artifact = agent_artifact_dir(store.run_dir(prior.id), "b", "b")
    artifact.mkdir(parents=True)
    prior_thread = node_thread(store.run_dir(prior.id), "b", "b")
    ThreadLog(prior_thread).append("user", "prior-turn", content="synthesize", llm_content="synthesize")
    (artifact / "report.md").write_text("Prior partial work")
    resumed = prior.model_copy(update={"id": "next", "status": RunStatus.pending})
    store.create_run(resumed)
    current = TaskStore(store.run_dir(resumed.id))
    for task in tasks:
        current.save_task(task)
    summaries = {}
    SwarmRuntime(store, policy=ToolPolicy.from_config(get_env_config()))._apply_resume_overlay(resumed, store.run_dir(resumed.id), current, prior, summaries)
    assert summaries == {"a": "Revenue $26B"}
    assert current.load_task("b").status == TaskStatus.pending
    copied = agent_artifact_dir(store.run_dir(resumed.id), "b", "b")
    assert node_thread(store.run_dir(resumed.id), "b", "b").read_bytes() == prior_thread.read_bytes()
    assert (copied / "report.md").read_text() == "Prior partial work"
    # Different questions must not inherit prior securities' completed research.
    changed = resumed.model_copy(update={"id": "different", "user_vars": {"target": "JPM"}})
    store.create_run(changed)
    current = TaskStore(store.run_dir(changed.id))
    for task in tasks:
        current.save_task(task)
    kept = {}
    SwarmRuntime(store, policy=ToolPolicy.from_config(get_env_config()))._apply_resume_overlay(changed, store.run_dir(changed.id), current, prior, kept)
    assert not kept
    assert not node_thread(store.run_dir(changed.id), "b", "b").exists()


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
    result = json.loads(SwarmTool(policy=ToolPolicy.from_config(get_env_config())).execute(prompt="Continue the unfinished work", resume_run_id=prior.id))
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
    items = ThreadLog(node_thread(tmp_path, "analyst", "task")).read()
    assert [item.get("content") for item in items if item.type == "assistant"][-1] == final


def test_pre_cutover_run_is_refused_before_preset_dispatch(tmp_path, monkeypatch):
    import pytest

    from src.swarm.models import RunStatus, SwarmRun
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore

    store = SwarmStore(base_dir=tmp_path)
    old = SwarmRun(
        id="pre-cutover", preset_name="demo", status=RunStatus.failed,
        created_at="2026-11-13T00:00:00Z",
    )
    store.create_run(old)
    runtime = SwarmRuntime(store, policy=ToolPolicy.from_config(get_env_config()))
    with pytest.raises(ValueError, match="before the AgentRuntime cutover"):
        runtime.start_run("demo", {}, resume_from=old)


def test_detached_mutation_stops_batch_and_refuses_retry(tmp_path, monkeypatch):
    from src.agent.tools import BaseTool, ToolRegistry
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore

    calls = []
    done = threading.Event()

    class MutatingTool(BaseTool):
        name = "write_probe"
        is_readonly = False


        def execute(self, **kwargs):
            calls.append(kwargs["operation"])
            done.wait(10)
            return '{"status":"ok"}'

    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(MutatingTool())
    model = Provider([
        LLMResponse(tool_calls=[
            ToolCallRequest("first", "write_probe", {"operation": "first"}),
            ToolCallRequest("second", "write_probe", {"operation": "second"}),
        ]),
    ])
    monkeypatch.setattr("src.swarm.node.ChatLLM", lambda **_: model)
    monkeypatch.setattr("src.swarm.node.build_swarm_registry", lambda *a, **k: registry)
    monkeypatch.setattr("src.product.tool_invocation._tool_timeout_seconds", lambda: 0.2)
    runtime = SwarmRuntime(SwarmStore(tmp_path), policy=registry.policy)
    events = []
    try:
        result = runtime._run_node_with_retries(
            SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="Research", max_retries=2),
            SwarmTask(id="task", agent_id="analyst", prompt_template="Analyze"),
            {}, {}, tmp_path, events.append, "run",
        )
    finally:
        done.set()
    assert result.error == UNKNOWN_TOOL_OUTCOME
    assert calls == ["first"]
    assert not any(event.type == "task_retry" for event in events)
    items = ThreadLog(node_thread(tmp_path, "analyst", "task")).read()
    outcomes = {item.get("tool_call_id"): json.loads(item.get("content"))
                for item in items if item.type == "tool_result"}
    assert outcomes["first"]["outcome"] == "unknown"
    assert outcomes["second"]["error_code"] == "tool_cancelled"


def test_resumed_node_replays_evidence_without_restoring_identity_authority(tmp_path, monkeypatch):
    from src.agent.tools import BaseTool, ToolRegistry
    from src.product.identity.ledger import IdentityLedger

    calls = []

    class Probe(BaseTool):
        name = "market_probe"

        def execute(self, **kwargs):
            calls.append(kwargs)
            return '{"status":"ok"}'

    workspace = agent_artifact_dir(tmp_path, "analyst", "task")
    workspace.mkdir(parents=True)
    identity = IdentityLedger(run_dir=workspace, user_message="Use AAPL.US.")
    assert "AAPL.US" in identity.authorized_symbols
    path = node_thread(tmp_path, "analyst", "task")
    log = ThreadLog(path)
    log.append("state", "older-attempt", workspace=str(workspace), identity=identity.export_state())
    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(Probe())
    model = Provider([
        LLMResponse(tool_calls=[ToolCallRequest("read", "market_probe", {"symbol": "AAPL.US"})]),
        LLMResponse(content="Fresh authorization is required."),
    ])
    result = run(tmp_path, registry, monkeypatch, model, resume=True)
    assert result.status == "completed"
    assert not calls
    receipts = [item for item in log.read() if item.type == "tool_result"]
    assert len(receipts) == 1 and receipts[0].get("status") == "error"


def test_checkpoint_retry_requires_a_fresh_identity_resolution(tmp_path, monkeypatch):
    from src.agent.tools import BaseTool, ToolRegistry

    lookups = []
    market_reads = []

    class Resolver(BaseTool):
        name = "search_symbol"
        is_readonly = True

        def execute(self, **kwargs):
            lookups.append(kwargs["query"])
            if len(lookups) == 1:
                return '{"ok":true,"data":{"query":"AAPL","candidates":[{"symbol":"AAPL.US","market":"us"}]}}'
            return '{"ok":false,"error":"Resolver unavailable"}'

    class MarketRead(BaseTool):
        name = "market_probe"
        is_readonly = True

        def execute(self, **kwargs):
            market_reads.append(kwargs)
            return '{"status":"ok"}'

    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(Resolver())
    registry.register(MarketRead())
    cached_reads = {}
    first = Provider([
        LLMResponse(tool_calls=[ToolCallRequest("lookup-1", "search_symbol", {"query": "AAPL"})]),
        fail_stream,
    ])
    assert run(tmp_path, registry, monkeypatch, first, successful_reads=cached_reads).status == "failed"

    second = Provider([
        LLMResponse(tool_calls=[
            ToolCallRequest("lookup-2", "search_symbol", {"query": "AAPL"}),
            ToolCallRequest("market-read", "market_probe", {"symbol": "AAPL.US"}),
        ]),
        LLMResponse(content="A fresh identity lookup was unavailable."),
    ])
    result = run(tmp_path, registry, monkeypatch, second, resume=True, successful_reads=cached_reads)

    assert result.status == "completed"
    assert not market_reads
    assert lookups == ["AAPL", "AAPL"]
