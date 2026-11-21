"""spawn_agent runs one isolated child agent and returns its final answer.

Parent and child are both driven by scripted offline LLMs; nothing here calls a
provider, broker or market-data source.
"""

from __future__ import annotations

import copy
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pytest
from pydantic import ValidationError

from src.agent.instrument_identity import IdentityLedger, agent_authored_request
from src.agent.loop import AgentLoop
from src.agent.progress import _set_emitter
from src.agent.tools import BaseTool, ToolRegistry
from src.config.accessor import get_env_config, reset_env_config
from src.providers.chat import LLMResponse, ToolCallRequest
from src.tools.spawn_agent_tool import (
    SUBAGENT_DIRNAME,
    SpawnAgentTool,
    child_exclusion,
    child_registry,
    is_trading_state_tool,
)
from src.tools.swarm_tool import SwarmTool

USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class ScriptedLLM:
    """Offline LLM: each request consumes the next scripted step."""

    model_name = "offline"

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    def stream_chat(self, messages, tools=None, should_cancel=None, **_: Any) -> LLMResponse:
        self.requests.append(
            {
                "messages": copy.deepcopy(messages),
                "tools": [t["function"]["name"] for t in tools or []],
            }
        )
        step = self.script.pop(0)
        return step(messages, tools, should_cancel) if callable(step) else step


def call(name: str, call_id: str = "c1", **arguments: Any) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCallRequest(id=call_id, name=name, arguments=arguments)],
        usage_metadata=dict(USAGE),
    )


def answer(text: str) -> LLMResponse:
    return LLMResponse(content=text, usage_metadata=dict(USAGE))


def wait_for_cancel(limit_s: float) -> Callable:
    """A provider call that runs until the loop asks it to stop, or ``limit_s``."""

    def step(messages, tools, should_cancel) -> LLMResponse:
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline:
            if should_cancel is not None and should_cancel():
                return LLMResponse(content="")
            time.sleep(0.02)
        return answer("finished after the full wait")

    return step


class RecordingTool(BaseTool):
    """A local tool double. The required argument keeps discovery from registering it."""

    description = "Offline test double."
    parameters = {"type": "object", "properties": {"symbol": {"type": "string"}, "n": {"type": "integer"}}}
    repeatable = True

    def __init__(self, name: str, *, is_readonly: bool = True, on_call: Callable | None = None) -> None:
        self.name = name
        self.is_readonly = is_readonly
        self.calls: list[dict[str, Any]] = []
        self._on_call = on_call

    def execute(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        if self._on_call is not None:
            self._on_call()
        return json.dumps({"status": "ok", "n": kwargs.get("n"), "call": len(self.calls)})


@pytest.fixture
def run_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    monkeypatch.setenv("VIBE_TRADING_TOOL_LOADING", "eager")
    reset_env_config()
    parent_dir = tmp_path / "parent-run"
    parent_dir.mkdir()
    return parent_dir


def parent_registry(child_llm: ScriptedLLM, *tools: BaseTool, cancel_event=None, **spawn_kwargs: Any) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    registry.register(
        SpawnAgentTool(registry, cancel_event=cancel_event, llm_factory=lambda: child_llm, **spawn_kwargs)
    )
    return registry


def run_parent(registry: ToolRegistry, script: list[Any], run_dir: Path, **kwargs: Any):
    llm = ScriptedLLM(script)
    events: list[tuple[str, dict]] = []
    loop = AgentLoop(
        registry=registry,
        llm=llm,
        event_callback=lambda name, data: events.append((name, copy.deepcopy(data))),
        max_iterations=6,
        **kwargs,
    )
    loop.memory.run_dir = str(run_dir)
    return loop, llm, events


def spawn_result(parent_llm: ScriptedLLM, call_id: str = "spawn") -> dict[str, Any]:
    """The spawn_agent tool message the parent's next request carried."""
    for request in parent_llm.requests:
        for message in request["messages"]:
            if message.get("role") == "tool" and message.get("tool_call_id") == call_id:
                return json.loads(message["content"])
    raise AssertionError("the parent never received the spawn_agent result")


def test_child_sees_only_the_task_and_the_parent_gets_its_answer(run_root: Path) -> None:
    child_llm = ScriptedLLM([answer("Child verdict: margins widened.")])
    registry = parent_registry(child_llm)
    task = "Summarize the margin trend described here: gross margin rose two years running."
    loop, parent_llm, events = run_parent(
        registry,
        [call("spawn_agent", "spawn", task=task, label="margins"), answer("Parent done.")],
        run_root,
    )

    result = loop.run(
        "PARENT-QUESTION delegate the margin summary",
        history=[{"role": "user", "content": "PARENT-HISTORY earlier turn"}],
    )

    assert result["status"] == "success"
    child_text = json.dumps(child_llm.requests[0]["messages"])
    assert task in child_text
    assert "PARENT-QUESTION" not in child_text
    assert "PARENT-HISTORY" not in child_text

    payload = spawn_result(parent_llm)
    assert payload["status"] == "ok"
    assert payload["content"] == "Child verdict: margins widened."
    assert payload["iterations"] == 1
    assert payload["label"] == "margins"
    # What the parent model reads, after tool-result redaction.
    assert payload["token_usage"] == {
        "total_input_tokens": 10,
        "total_output_tokens": 5,
        "calls": 1,
        "unreported_calls": 0,
        "token_source": "provider",
    }
    child_dir = Path(payload["run_dir"])
    assert child_dir.parent == run_root.resolve() / SUBAGENT_DIRNAME
    # The child's bookkeeping lives in its own directory, never over the parent's.
    assert json.loads((child_dir / "req.json").read_text())["prompt"] == task
    assert json.loads((run_root / "req.json").read_text())["prompt"].startswith("PARENT-QUESTION")

    # Progress reaches the parent as tool name and status; child text does not.
    deltas = "".join(d.get("delta", "") for name, d in events if name == "text_delta")
    assert "Child verdict" not in deltas
    stages = [d.get("stage") for name, d in events if name == "tool_progress"]
    assert "subagent_started" in stages and "subagent_finished" in stages


def test_a_file_the_child_writes_is_readable_by_the_parent(run_root: Path) -> None:
    from src.tools.read_file_tool import ReadFileTool
    from src.tools.write_file_tool import WriteFileTool

    child_llm = ScriptedLLM(
        [call("write_file", path="notes.md", content="child findings"), answer("Wrote notes.md.")]
    )
    registry = parent_registry(child_llm, WriteFileTool())

    payload = json.loads(registry.get("spawn_agent").execute(task="Write notes.md.", run_dir=str(run_root)))

    assert payload["status"] == "ok"
    read = json.loads(
        ReadFileTool().execute(path=f"{payload['relative_run_dir']}/notes.md", run_dir=str(run_root))
    )
    assert read["content"].strip().endswith("child findings")


def test_child_progress_carries_tool_names_and_statuses_only(run_root: Path) -> None:
    probe = RecordingTool("probe_read")
    child_llm = ScriptedLLM([call("probe_read", n=1), answer("SECRET-CHILD-TEXT")])
    registry = parent_registry(child_llm, probe)
    received = []
    _set_emitter(received.append)
    try:
        payload = json.loads(registry.get("spawn_agent").execute(task="Read the probe once.", run_dir=str(run_root)))
    finally:
        _set_emitter(None)

    assert payload["status"] == "ok"
    messages = [(event.stage, event.message) for event in received]
    assert ("subagent_tool", "probe_read: running") in messages
    assert ("subagent_tool", "probe_read: ok") in messages
    assert all("SECRET-CHILD-TEXT" not in message for _, message in messages)


def test_a_child_cannot_spawn_or_run_a_swarm(run_root: Path) -> None:
    child_llm = ScriptedLLM([call("spawn_agent", task="nested"), answer("Could not nest.")])
    registry = parent_registry(child_llm)
    registry.register(SwarmTool())
    spawned: list[str] = []
    original = SpawnAgentTool.execute

    def counting(self, **kwargs):
        spawned.append(kwargs.get("task"))
        return original(self, **kwargs)

    tool = registry.get("spawn_agent")
    tool.execute = counting.__get__(tool)

    payload = json.loads(tool.execute(task="Try to delegate further.", run_dir=str(run_root)))

    assert payload["status"] == "ok"
    assert spawned == ["Try to delegate further."]
    offered = child_llm.requests[0]["tools"]
    assert "spawn_agent" not in offered and "run_swarm" not in offered
    nested = json.loads(child_llm.requests[1]["messages"][-1]["content"])
    assert nested["status"] == "error" and "not found" in nested["error"]


def _bound_values(tool: BaseTool) -> list[Any]:
    """Every attribute value a (possibly wrapped) tool instance holds."""
    inner = getattr(tool, "_tool", tool)
    return list(vars(inner).values())


@pytest.mark.parametrize("include_shell_tools", [False, True])
def test_child_registry_enumeration_has_no_order_path_under_either_shell_configuration(
    tmp_path: Path, include_shell_tools: bool
) -> None:
    from src.memory.persistent import PersistentMemory
    from src.tools import build_registry

    def parent_callback(name, data):
        return None

    memory = PersistentMemory(memory_dir=tmp_path / "memory")
    parent = build_registry(
        include_shell_tools=include_shell_tools,
        session_id="PARENT-SESSION",
        event_callback=parent_callback,
        persistent_memory=memory,
    )
    child = child_registry(parent, tmp_path)
    dropped = set(parent.tool_names) - set(child.tool_names)

    assert {"spawn_agent", "run_swarm", "trading_place_order", "trading_cancel_order"} <= dropped
    assert "trading_select_connection" in dropped
    # Shell and background tools could start another agent or invoke arbitrary
    # trading code, so they are excluded even when the CLI enables them.
    shell_tools = {"bash", "background_run", "check_background", "cancel_background"}
    if include_shell_tools:
        assert shell_tools <= dropped
    else:
        assert {"bash", "background_run", "cancel_background"}.isdisjoint(parent.tool_names)
        assert "check_background" in dropped
    # Session-bound tools would act on the parent's goal; memory and skill
    # writers would shape the user's later prompts.
    assert {
        "start_research_goal", "get_research_goal", "update_research_goal_status",
        "update_research_goal", "add_goal_evidence", "run_research_autopilot",
        "scheduled_research", "remember", "save_skill", "patch_skill", "delete_skill",
        "skill_file",
    } <= dropped
    # Read-only broker tools are not trading state changes.
    assert "trading_positions" in child and "trading_orders" in child
    # Every non-readonly tool from a trading or live module stays with the parent,
    # whatever its name: a new order tool outside the broker prefixes fails here.
    trading_modules = ("src.tools.trading_connector_tool", "src.trading", "src.live")
    for name in parent.tool_names:
        tool = parent.get(name)
        if type(tool).__module__.startswith(trading_modules) and not tool.is_readonly:
            assert name not in child, f"{name} changes trading state but reached the child"
    # No tool the child keeps is bound to the parent's session, event stream
    # or persistent memory.
    for name in child.tool_names:
        held = _bound_values(child.get(name))
        assert "PARENT-SESSION" not in held, f"{name} is bound to the parent's session"
        assert all(value is not parent_callback for value in held), f"{name} emits on the parent's stream"
        assert all(value is not memory for value in held), f"{name} holds the user's persistent memory"
    # Nothing is lost without a reason.
    for name in dropped:
        assert child_exclusion(parent.get(name)) is not None, name

    # Enumerate the actual child registry, including wrappers, and apply the
    # same order-state identification rule used by the tool policy.
    reachable_order_tools = [
        name for name in child.tool_names if is_trading_state_tool(child.get(name))
    ]
    assert reachable_order_tools == []
    assert not {"spawn_agent", "run_swarm", "bash", "background_run"} & set(child.tool_names)


def test_parent_run_usage_artifact_includes_child_provider_calls(run_root: Path) -> None:
    child_llm = ScriptedLLM([answer("Child done.")])
    registry = parent_registry(child_llm)
    loop, _, events = run_parent(
        registry,
        [call("spawn_agent", "spawn", task="Answer once."), answer("Parent done.")],
        run_root,
    )

    result = loop.run("Delegate once.")

    assert result["status"] == "success"
    usage = json.loads((run_root / "llm_usage.json").read_text(encoding="utf-8"))
    assert usage["totals"]["total_tokens"] == 3 * USAGE["total_tokens"]
    assert sum(
        1 for entry in usage["per_iteration"] if entry.get("purpose") == "subagent"
    ) == 1
    child_events = [data for name, data in events if name == "llm_usage" and data.get("purpose") == "subagent"]
    assert len(child_events) == 1
    assert "call_index" not in child_events[0]


def test_parent_loop_charges_child_usage_to_the_active_goal_once(run_root: Path, goal_db) -> None:
    from src.goal import GoalStore

    goal = start_goal("S1", token_budget=20)
    child_llm = ScriptedLLM([answer("Child done.")])
    registry = parent_registry(child_llm, session_id="S1")
    loop, _, _ = run_parent(
        registry,
        [call("spawn_agent", "spawn", task="Answer once."), answer("Parent done.")],
        run_root,
    )

    loop.run("Delegate once.", session_id="S1")

    stored = GoalStore().get_goal(goal.goal_id)
    # The parent provider call and the child provider call are both charged,
    # while the child does not maintain a second goal meter.
    assert stored.tokens_used == 2 * USAGE["total_tokens"]
    assert stored.status.value == "budget_limited"


def test_trading_state_does_not_depend_on_the_broker_prefix_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config.env_schema import LLMConfig

    class ModuleOrderTool(RecordingTool):
        __module__ = "src.trading.probe"

    monkeypatch.setattr(LLMConfig.model_fields["claude_cli_deny_tool_prefixes"], "default", "")

    assert is_trading_state_tool(ModuleOrderTool("submit_probe_order", is_readonly=False))
    assert not is_trading_state_tool(ModuleOrderTool("read_probe_orders", is_readonly=True))


def test_trading_state_identification_survives_child_workspace_wrapping(tmp_path: Path) -> None:
    class ModuleOrderTool(RecordingTool):
        __module__ = "src.trading.probe"

    # Build the same wrapper used for a child registry around a non-prefixed
    # trading-state tool. The identification rule must inspect its source.
    from src.tools.spawn_agent_tool import _WorkspaceTool

    source = ModuleOrderTool("submit_probe_order", is_readonly=False)
    wrapped_tool = _WorkspaceTool(source, tmp_path)
    assert is_trading_state_tool(wrapped_tool)


def _remote_tool(name: str, annotations: Any) -> BaseTool:
    from src.tools.mcp import MCPRemoteTool, MCPRemoteToolSpec

    spec = MCPRemoteToolSpec(
        server_name="probe", remote_name=name, local_name=f"mcp_probe_{name}",
        description="Offline MCP double.", parameters={"type": "object", "properties": {}},
        annotations=annotations,
    )
    return MCPRemoteTool(object(), spec)


def test_only_an_mcp_tool_declared_read_only_reaches_the_child(tmp_path: Path) -> None:
    from mcp.types import ToolAnnotations

    parent = ToolRegistry()
    for tool in (
        _remote_tool("quotes", ToolAnnotations(readOnlyHint=True)),
        _remote_tool("submit", ToolAnnotations(readOnlyHint=False)),
        _remote_tool("unknown", None),
    ):
        parent.register(tool)

    child = child_registry(parent, tmp_path)

    assert child.tool_names == ["mcp_probe_quotes"]


def test_a_mandate_gated_live_order_tool_is_trading_state_under_any_name() -> None:
    from src.live.order_guard import LiveOrderGuardTool

    gated = object.__new__(LiveOrderGuardTool)
    gated.name = "mcp_rh_place_equity_order"

    assert is_trading_state_tool(gated)
    assert not is_trading_state_tool(RecordingTool("trading_positions_probe", is_readonly=True))
    assert is_trading_state_tool(RecordingTool("etoro_probe_write", is_readonly=False))
    assert not is_trading_state_tool(RecordingTool("write_probe", is_readonly=False))


def test_the_description_tells_the_model_not_to_delegate_a_trade() -> None:
    text = SpawnAgentTool.description
    assert "places, modifies or cancels orders" in text
    assert "never delegate a trade" in text
    assert SpawnAgentTool.is_readonly is False


def test_child_must_resolve_symbols_named_in_its_task(run_root: Path) -> None:
    quote = RecordingTool("probe_quote")
    child_llm = ScriptedLLM([call("probe_quote", symbol="600519.SH"), answer("Blocked, as expected.")])
    registry = parent_registry(child_llm, quote)

    payload = json.loads(
        registry.get("spawn_agent").execute(task="Fetch the latest quote for 600519.SH.", run_dir=str(run_root))
    )

    assert payload["status"] == "ok"
    assert quote.calls == []
    refused = json.loads(child_llm.requests[1]["messages"][-1]["content"])
    assert refused["error_code"] == "identity_required"


def test_only_an_agent_written_request_skips_symbol_seeding(tmp_path: Path) -> None:
    user = IdentityLedger(run_dir=tmp_path / "user", user_message="Quote 600519.SH")
    with agent_authored_request():
        agent = IdentityLedger(run_dir=tmp_path / "agent", user_message="Quote 600519.SH")
    after = IdentityLedger(run_dir=tmp_path / "after", user_message="Quote 600519.SH")

    assert user.authorized_symbols == {"600519.SH"}
    assert agent.authorized_symbols == set()
    assert after.authorized_symbols == {"600519.SH"}


def test_parent_cancel_stops_the_child_promptly(run_root: Path) -> None:
    parent_cancel = threading.Event()
    child_llm = ScriptedLLM([wait_for_cancel(limit_s=10)])
    registry = parent_registry(child_llm, cancel_event=parent_cancel)
    threading.Timer(0.3, parent_cancel.set).start()

    started = time.monotonic()
    payload = json.loads(registry.get("spawn_agent").execute(task="Think for a long time.", run_dir=str(run_root)))

    assert time.monotonic() - started < 3
    assert payload["status"] == "error"
    assert payload["error_code"] == "subagent_cancelled"
    assert payload["child_status"] == "cancelled"


def test_child_timeout_is_an_error_result(run_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBAGENT_TIMEOUT", "0.4")
    reset_env_config()
    child_llm = ScriptedLLM([wait_for_cancel(limit_s=10)])
    registry = parent_registry(child_llm)

    started = time.monotonic()
    payload = json.loads(registry.get("spawn_agent").execute(task="Never finish.", run_dir=str(run_root)))

    assert time.monotonic() - started < 3
    assert payload["status"] == "error"
    assert payload["error_code"] == "subagent_timeout"


def test_child_failure_is_a_tool_error_and_the_parent_turn_finishes(run_root: Path) -> None:
    def boom(messages, tools, should_cancel):
        raise RuntimeError("child provider exploded")

    child_llm = ScriptedLLM([boom])
    registry = parent_registry(child_llm)
    loop, parent_llm, _ = run_parent(
        registry,
        [call("spawn_agent", "spawn", task="Do a thing."), answer("Parent recovered.")],
        run_root,
    )

    result = loop.run("Delegate a thing.")

    assert result["status"] == "success"
    assert result["content"] == "Parent recovered."
    payload = spawn_result(parent_llm)
    assert payload["status"] == "error"
    assert payload["error_code"] == "subagent_failed"
    assert "child provider exploded" in payload["error"]


def test_a_child_that_cannot_start_is_a_tool_error(run_root: Path) -> None:
    def no_llm():
        raise RuntimeError("no provider configured")

    registry = ToolRegistry()
    registry.register(SpawnAgentTool(registry, llm_factory=no_llm))

    payload = json.loads(registry.get("spawn_agent").execute(task="Anything.", run_dir=str(run_root)))

    assert payload["status"] == "error"
    assert payload["error_code"] == "subagent_start_failed"
    assert "no provider configured" in payload["error"]


def test_child_iteration_cap_comes_from_config(run_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBAGENT_MAX_ITER", "3")
    reset_env_config()
    probe = RecordingTool("probe_read")
    counter = iter(range(100))

    def keep_reading(messages, tools, should_cancel):
        if not tools:
            return answer("Out of budget; here is what I have.")
        return call("probe_read", f"r{next(counter)}", n=next(counter))

    child_llm = ScriptedLLM([keep_reading] * 10)
    registry = parent_registry(child_llm, probe)

    payload = json.loads(registry.get("spawn_agent").execute(task="Read forever.", run_dir=str(run_root)))

    assert len(child_llm.requests) == 3
    assert child_llm.requests[-1]["tools"] == []
    assert payload["iterations"] == 3
    assert payload["max_iterations"] == 3
    assert payload["content"] == "Out of budget; here is what I have."


def test_task_is_required(run_root: Path) -> None:
    registry = ToolRegistry()
    registry.register(SpawnAgentTool(registry, llm_factory=lambda: ScriptedLLM([])))

    payload = json.loads(registry.get("spawn_agent").execute(task="  ", run_dir=str(run_root)))

    assert payload["status"] == "error" and payload["error_code"] == "invalid_arguments"


def test_a_run_dir_outside_the_run_roots_is_refused(run_root: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("elsewhere")
    child_llm = ScriptedLLM([answer("never runs")])
    registry = parent_registry(child_llm)

    payload = json.loads(registry.get("spawn_agent").execute(task="Anything.", run_dir=str(outside)))

    assert payload["error_code"] == "outside_run_roots"
    assert child_llm.requests == []
    assert not (outside / SUBAGENT_DIRNAME).exists()


def test_build_registry_hands_spawn_agent_its_registry_cancel_event_and_session() -> None:
    from src.tools import build_registry

    def sink(name, data):
        return None

    cancel = threading.Event()
    registry = build_registry(cancel_event=cancel, session_id="S-BUILD", event_callback=sink)
    tool = registry.get("spawn_agent")

    assert isinstance(tool, SpawnAgentTool)
    assert tool._registry is registry
    assert tool._cancel_event is cancel
    assert tool._session_id == "S-BUILD"
    assert tool._event_callback is sink


@pytest.mark.parametrize(("name", "value"), [("SUBAGENT_MAX_ITER", "0"), ("SUBAGENT_TIMEOUT", "-1")])
def test_subagent_budget_rejects_out_of_range_values(monkeypatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)
    reset_env_config()
    with pytest.raises(ValidationError):
        get_env_config()


def test_subagent_budget_defaults_match_a_swarm_worker(monkeypatch) -> None:
    for name in ("SUBAGENT_MAX_ITER", "SUBAGENT_TIMEOUT", "SWARM_WORKER_MAX_ITER", "SWARM_WORKER_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    reset_env_config()
    config = get_env_config()

    assert config.agent_tuning.subagent_max_iter == config.swarm.swarm_worker_max_iter == 50
    assert config.agent_tuning.subagent_timeout == config.swarm.swarm_worker_timeout == 300


@pytest.fixture
def goal_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    reset_env_config()


def start_goal(session_id: str, **budget: Any):
    from src.goal import GoalStore

    return GoalStore().replace_goal(
        session_id=session_id, objective="PARENT-GOAL compare bank margins", criteria=["margin trend"], **budget
    )


def test_a_child_cannot_read_or_change_the_parents_research_goal(run_root: Path, goal_db) -> None:
    from src.goal import GoalStore
    from src.tools.goal_tool import GetResearchGoalTool, UpdateResearchGoalStatusTool

    events: list[str] = []

    def parent_callback(name: str, data: dict) -> None:
        events.append(name)

    goal = start_goal("S1")
    goal_tools = [
        cls(default_session_id="S1", event_callback=parent_callback)
        for cls in (GetResearchGoalTool, UpdateResearchGoalStatusTool)
    ]
    child_llm = ScriptedLLM([
        call("get_research_goal"),
        call("update_research_goal_status", "c2", status="paused", recap="child paused it"),
        answer("Done."),
    ])
    registry = parent_registry(
        child_llm, *goal_tools, session_id="S1", event_callback=parent_callback
    )

    payload = json.loads(registry.get("spawn_agent").execute(task="An unrelated sub-task.", run_dir=str(run_root)))

    assert payload["status"] == "ok"
    assert "get_research_goal" not in child_llm.requests[0]["tools"]
    for index in (1, 2):
        refused = json.loads(child_llm.requests[index]["messages"][-1]["content"])
        assert refused["status"] == "error" and "not found" in refused["error"]
    assert "PARENT-GOAL" not in json.dumps([r["messages"] for r in child_llm.requests])
    stored = GoalStore().get_goal(goal.goal_id)
    assert stored.status.value == "active"
    # The child's three provider calls are the goal's spend, and nothing else
    # about the goal moved: only usage updates reached the parent's stream.
    assert stored.tokens_used == 3 * USAGE["total_tokens"]
    assert set(events) == {"goal.updated", "llm_usage"}


def test_child_usage_is_charged_to_the_goal_and_stops_the_child_at_its_budget(run_root: Path, goal_db) -> None:
    from src.goal import GoalStore

    goal = start_goal("S1", token_budget=20)
    probe = RecordingTool("probe_read")
    child_llm = ScriptedLLM([
        call("probe_read", "r1", n=1),
        call("probe_read", "r2", n=2),
        call("probe_read", "r3", n=3),
        answer("never reached"),
    ])
    registry = parent_registry(child_llm, probe, session_id="S1")

    payload = json.loads(registry.get("spawn_agent").execute(task="Read three times.", run_dir=str(run_root)))

    assert payload["status"] == "error"
    assert payload["error_code"] == "goal_token_budget_exhausted"
    stored = GoalStore().get_goal(goal.goal_id)
    assert stored.tokens_used == 2 * USAGE["total_tokens"]
    assert stored.status.value == "budget_limited"
    assert len(child_llm.requests) == 2


def test_no_child_starts_once_the_goal_budget_is_spent(run_root: Path, goal_db) -> None:
    from src.goal import GoalStore

    goal = start_goal("S1", token_budget=10)
    GoalStore().account_usage(session_id="S1", goal_id=goal.goal_id, expected_goal_id=goal.goal_id, token_delta=10)
    child_llm = ScriptedLLM([answer("never runs")])
    registry = parent_registry(child_llm, session_id="S1")

    payload = json.loads(registry.get("spawn_agent").execute(task="Anything.", run_dir=str(run_root)))

    assert payload["error_code"] == "goal_token_budget_exhausted"
    assert child_llm.requests == []
    assert not (run_root / SUBAGENT_DIRNAME).exists()


def test_child_usage_reaches_the_parent_stream_without_a_parent_call_key(run_root: Path, tmp_path: Path) -> None:
    from src.live.runtime.decision_budget import DecisionBudget, DecisionBudgetError, DecisionSettings

    events: list[tuple[str, dict]] = []
    child_llm = ScriptedLLM([answer("Child done.")])
    registry = parent_registry(child_llm, event_callback=lambda name, data: events.append((name, dict(data))))

    json.loads(registry.get("spawn_agent").execute(task="Answer once.", run_dir=str(run_root)))

    usage = [data for name, data in events if name == "llm_usage"]
    assert len(usage) == 1
    assert usage[0]["purpose"] == "subagent"
    assert usage[0]["total_tokens"] == USAGE["total_tokens"]
    assert "call_index" not in usage[0] and "iter" not in usage[0]
    # The live decision budget keys usage by the parent's call index. A child
    # call must be refused there, never ignored as a call it already counted.
    budget = DecisionBudget("probe", path=tmp_path / "decisions.sqlite3")
    settings = DecisionSettings()
    now = datetime.now(timezone.utc)
    decision = budget.begin(settings, now)
    budget.record(decision, {"iter": 1, "call_index": 1, **USAGE}, settings, now)
    with pytest.raises(DecisionBudgetError):
        budget.record(decision, usage[0], settings, now)


@pytest.mark.parametrize(
    "arguments",
    [
        {"path": "req.json", "run_dir": "../.."},
        {"path": "../../req.json"},
        {"path": "{parent}/req.json"},
    ],
    ids=["run_dir-up", "path-up", "absolute-path"],
)
def test_a_child_cannot_write_outside_its_workspace(
    run_root: Path, arguments: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.tools.write_file_tool import WriteFileTool

    # As in production, where the runs root is a write root: the parent
    # itself may write here, so only the child's confinement refuses it.
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_WRITE_ROOTS", str(run_root.parent))
    reset_env_config()
    parent_req = run_root / "req.json"
    parent_req.write_text('{"prompt": "PARENT"}', encoding="utf-8")
    arguments = {k: v.replace("{parent}", str(run_root)) for k, v in arguments.items()}
    child_llm = ScriptedLLM([call("write_file", content="OVERWRITTEN", **arguments), answer("Tried.")])
    registry = parent_registry(child_llm, WriteFileTool())

    payload = json.loads(registry.get("spawn_agent").execute(task="Write req.json.", run_dir=str(run_root)))

    assert payload["status"] == "ok"
    refused = json.loads(child_llm.requests[1]["messages"][-1]["content"])
    assert refused["status"] == "error"
    assert parent_req.read_text(encoding="utf-8") == '{"prompt": "PARENT"}'


def test_a_child_tool_pointed_outside_its_workspace_does_not_run(run_root: Path) -> None:
    probe = RecordingTool("probe_read")
    child_llm = ScriptedLLM([call("probe_read", n=1, run_dir="../.."), answer("Refused.")])
    registry = parent_registry(child_llm, probe)

    json.loads(registry.get("spawn_agent").execute(task="Read the parent.", run_dir=str(run_root)))

    assert probe.calls == []
    refused = json.loads(child_llm.requests[1]["messages"][-1]["content"])
    assert refused["error_code"] == "outside_subagent_workspace"


@pytest.mark.parametrize("stop", ["timeout", "parent_cancel"])
def test_a_stop_ends_the_wait_for_a_running_tool_call_then_ends_the_child(
    run_root: Path, monkeypatch: pytest.MonkeyPatch, stop: str
) -> None:
    # The child is cancelled and the parent stops waiting at the hard tool
    # boundary. The in-process write worker may finish in the background, but
    # the child asks its model nothing after cancellation.
    parent_cancel = threading.Event()
    if stop == "timeout":
        monkeypatch.setenv("SUBAGENT_TIMEOUT", "0.2")
        reset_env_config()
    else:
        threading.Timer(0.2, parent_cancel.set).start()
    slow = RecordingTool("slow_write", is_readonly=False, on_call=lambda: time.sleep(1.0))
    child_llm = ScriptedLLM([call("slow_write", n=1), answer("never asked")])
    registry = parent_registry(child_llm, slow, cancel_event=parent_cancel)

    started = time.monotonic()
    payload = json.loads(registry.get("spawn_agent").execute(task="Write slowly.", run_dir=str(run_root)))

    assert time.monotonic() - started < 1.0
    assert len(slow.calls) == 1
    assert len(child_llm.requests) == 1
    assert payload["error_code"] == ("subagent_timeout" if stop == "timeout" else "subagent_cancelled")


def test_stopping_the_child_never_sets_the_parents_cancel_flag(run_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBAGENT_TIMEOUT", "0.3")
    reset_env_config()
    parent_cancel = threading.Event()
    child_llm = ScriptedLLM([wait_for_cancel(limit_s=10)])
    registry = parent_registry(child_llm, cancel_event=parent_cancel)

    payload = json.loads(registry.get("spawn_agent").execute(task="Think for a long time.", run_dir=str(run_root)))

    assert payload["error_code"] == "subagent_timeout"
    assert not parent_cancel.is_set()
