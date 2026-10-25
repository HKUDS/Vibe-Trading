"""Deferred schemas retain discoverability, exact contracts, and execution gates."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

from src.agent.context import ContextBuilder, _SYSTEM_PROMPT
from src.agent.context_budget import ContextMeter
from src.agent.loop import AgentLoop
from src.agent.memory import WorkspaceMemory
from src.agent.tool_loading import DeferredToolRegistry, prepare_registry, request_definitions
from src.agent.tools import BaseTool, ToolRegistry
from src.providers.chat import LLMResponse, ToolCallRequest


class ExampleTool(BaseTool):
    description = "Read a named test observation."
    parameters = {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}

    def __init__(self, name):
        self.name = name
        self.calls = []

    def execute(self, label, **kwargs):
        self.calls.append(label)
        return json.dumps({"status": "ok", "observation": label})


def registry():
    source = ToolRegistry()
    for index in range(18):
        source.register(ExampleTool(f"read_observation_{index}"))
    return source


def test_every_tool_is_visible_and_loading_preserves_exact_schema():
    source = registry()
    deferred = DeferredToolRegistry(source)
    assert [d["function"]["name"] for d in request_definitions(deferred)] == ["load_tools"]
    assert all(f"- {name}:" in deferred.catalog() for name in source.tool_names)
    assert deferred.expose(["read_observation_17", "read_observation_2"])["status"] == "ok"
    offered = {d["function"]["name"]: d for d in request_definitions(deferred)}
    assert offered["read_observation_17"] == source.get("read_observation_17").to_openai_schema()
    assert offered["read_observation_2"] == source.get("read_observation_2").to_openai_schema()
    assert source.get("read_observation_17").calls == []
    assert "load_tools" not in source
    assert len(deferred.get_definitions()) == len(source) + 1  # Full manifest.


def test_loading_message_uses_the_host_tool_protocol():
    deferred = DeferredToolRegistry(registry())

    result = deferred.expose(["read_observation_2"])

    assert result["message"] == (
        "Full schemas are available in the next request. Request them through "
        "the host's tool-call protocol in your next reply; loading has not executed them."
    )
    assert "host's tool-call protocol" in deferred.get("load_tools").description
    prompt = ContextBuilder(deferred, WorkspaceMemory()).build_system_prompt()
    assert "then request them through the host's tool-call protocol" in prompt
    assert "then call them directly" not in prompt


def test_loading_cannot_add_a_tool_outside_the_current_registry():
    deferred = DeferredToolRegistry(registry())
    before = request_definitions(deferred)
    rejected = deferred.expose(["read_observation_2", "trading_place_order"])
    assert rejected["status"] == "error"
    assert request_definitions(deferred) == before
    assert "trading_place_order" not in deferred


def test_independent_runs_do_not_share_exposed_schemas():
    source = registry()
    first, second = DeferredToolRegistry(source), DeferredToolRegistry(source)
    first.expose(["read_observation_2"])
    assert len(request_definitions(first)) == 2
    assert len(request_definitions(second)) == 1
    first.reset_exposure()
    assert len(request_definitions(first)) == 1


def test_new_schemas_append_without_reordering_the_existing_prefix():
    deferred = DeferredToolRegistry(registry())
    deferred.expose(["read_observation_17"])
    prefix = request_definitions(deferred)
    deferred.expose(["read_observation_0", "read_observation_17"])
    assert request_definitions(deferred)[:len(prefix)] == prefix


def test_eager_escape_hatch_and_small_registries_stay_unchanged(monkeypatch):
    source = registry()
    monkeypatch.setenv("VIBE_TRADING_TOOL_LOADING", "eager")
    assert prepare_registry(source) is source


def test_deferred_prompt_retains_grounding_and_every_skill_name():
    eager = ContextBuilder(registry(), WorkspaceMemory())
    lazy = ContextBuilder(DeferredToolRegistry(registry()), WorkspaceMemory())
    original, compact = eager.build_system_prompt(), lazy.build_system_prompt()
    assert original.split("## Guidelines", 1)[1].split("## Current Date", 1)[0] == compact.split("## Guidelines", 1)[1].split("## Current Date", 1)[0]
    assert original.split("## Output Principles", 1)[1].split("## Tools", 1)[0] == compact.split("## Output Principles", 1)[1].split("## Tools", 1)[0]
    assert all(skill.name in compact for skill in lazy.skills_loader.skills)
    assert "No catalog entry is hidden" in compact
    assert "Layer 2" in compact
    assert "MUST" in _SYSTEM_PROMPT


def test_new_schemas_change_measured_context_size_without_double_counting():
    messages = [{"role": "system", "content": "fixed"}, {"role": "user", "content": "question"}]
    meter = ContextMeter()
    meter.observe(8_000, messages, tool_schema_tokens=600)
    assert meter.tokens(messages, 600) == 8_000
    assert meter.tokens(messages, 1_600) == 9_000
    assert meter.static(messages, 1_600) - meter.static(messages, 600) == 1_000
    meter.observe(9_000, messages, tool_schema_tokens=1_600)
    assert meter.tokens(messages, 1_600) == 9_000
    assert meter.tokens(messages, 0) == 7_400


def test_real_loop_loads_then_calls_the_original_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_TOOL_LOADING", "lazy")
    source = registry()
    responses = [
        LLMResponse(tool_calls=[ToolCallRequest(id="load", name="load_tools", arguments={"names": ["read_observation_17"]})]),
        LLMResponse(tool_calls=[ToolCallRequest(id="read", name="read_observation_17", arguments={"label": "verified"})]),
        LLMResponse(content="The observation is verified."),
    ]
    llm = SimpleNamespace(model_name="offline", stream_chat=Mock(side_effect=responses))
    agent = AgentLoop(source, llm, max_iterations=5)
    agent.memory.run_dir = str(tmp_path)
    result = agent.run("Read the observation and summarize it.")
    assert result["status"] == "success"
    assert source.get("read_observation_17").calls == ["verified"]
    requests = llm.stream_chat.call_args_list
    assert [t["function"]["name"] for t in requests[0].kwargs["tools"]] == ["load_tools"]
    assert "read_observation_17" in [t["function"]["name"] for t in requests[1].kwargs["tools"]]


def test_loops_do_not_share_schema_state_when_given_the_same_wrapper():
    shared = DeferredToolRegistry(registry())
    first = AgentLoop(shared, SimpleNamespace())
    second = AgentLoop(shared, SimpleNamespace())
    first.registry.expose(["read_observation_2"])
    assert len(request_definitions(first.registry)) == 2
    assert len(request_definitions(second.registry)) == 1
    assert len(request_definitions(shared)) == 1
