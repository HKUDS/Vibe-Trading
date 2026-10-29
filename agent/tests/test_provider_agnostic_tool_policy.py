"""Provider-agnostic deny lists and bash screening (#2085)."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from src.agent.context import ContextBuilder
from src.agent.loop import AgentLoop
from src.agent.tools import BaseTool, ToolRegistry
from src.agent.trace import TraceWriter
from src.config.accessor import get_env_config, reset_env_config
from src.providers.chat import ChatLLM
from src.providers.llm import provider_diagnostics
from src.providers.tool_policy import bash_policy, policy_status
from src.providers import tool_policy
from tests.module_os_helpers import patch_module_os

_POLICY_ENV = (
    "VIBE_TRADING_DENY_TOOL_PREFIXES",
    "VIBE_TRADING_BASH_POLICY",
    "CLAUDE_CLI_DENY_TOOL_PREFIXES",
    "CLAUDE_CLI_BASH_POLICY",
)


@pytest.fixture(autouse=True)
def clean_policy_env(monkeypatch: pytest.MonkeyPatch):
    for name in _POLICY_ENV:
        monkeypatch.delenv(name, raising=False)
    reset_env_config()
    yield
    reset_env_config()


@pytest.fixture
def shared_policy(monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_DENY_TOOL_PREFIXES", "trading_,etoro_")
    monkeypatch.setenv("VIBE_TRADING_BASH_POLICY", "python-only")
    reset_env_config()


def _tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "test tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


class _RecordingLLM:
    def __init__(self) -> None:
        self.bound_tools: list[dict] | None = None

    def bind_tools(self, tools: list[dict]) -> _RecordingLLM:
        self.bound_tools = tools
        return self

    def invoke(self, messages: list[dict], **kwargs: object) -> AIMessage:
        return AIMessage(content="ok")

    def stream(self, messages: list[dict], **kwargs: object):
        yield AIMessageChunk(content="ok", response_metadata={"finish_reason": "stop"})


def _chat(llm: _RecordingLLM) -> ChatLLM:
    chat = ChatLLM.__new__(ChatLLM)
    chat._llm = llm
    chat.model_name = "gpt-test"
    return chat


def test_chat_filters_denied_tools_before_any_provider_binds(shared_policy) -> None:
    llm = _RecordingLLM()

    _chat(llm).chat(
        [{"role": "user", "content": "x"}],
        tools=[
            _tool("get_market_data"),
            _tool("trading_place_order"),
            _tool("etoro_close_position"),
        ],
    )

    assert llm.bound_tools is not None
    assert [item["function"]["name"] for item in llm.bound_tools] == ["get_market_data"]


def test_stream_chat_uses_the_same_provider_agnostic_filter(shared_policy) -> None:
    llm = _RecordingLLM()

    response = _chat(llm).stream_chat(
        [{"role": "user", "content": "x"}],
        tools=[_tool("get_market_data"), _tool("trading_place_order")],
    )

    assert response.content == "ok"
    assert llm.bound_tools is not None
    assert [item["function"]["name"] for item in llm.bound_tools] == ["get_market_data"]


class _FakeBashTool(BaseTool):
    name = "bash"
    description = "recording bash double"
    parameters: dict = {"type": "object", "properties": {}}
    is_readonly = False

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[dict] = []

    def execute(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return json.dumps({"status": "ok", "arguments": kwargs})


def _agent(tool: BaseTool, tmp_path) -> AgentLoop:
    registry = ToolRegistry()
    registry.register(tool)
    agent = AgentLoop(
        registry=registry,
        llm=SimpleNamespace(),
        max_iterations=2,
        event_callback=lambda name, data: None,
    )
    agent.memory.run_dir = str(tmp_path)
    return agent


def _call(agent: AgentLoop, name: str, arguments: dict, tmp_path) -> list[dict]:
    messages: list[dict] = []
    trace = TraceWriter(tmp_path)
    agent._process_tool_calls(
        [SimpleNamespace(id="call-1", name=name, arguments=arguments)],
        ContextBuilder,
        messages,
        trace,
        [],
        1,
    )
    trace.close()
    return messages


def test_shared_execution_rejects_bash_without_running_it(tmp_path, shared_policy) -> None:
    tool = _FakeBashTool("bash")
    agent = _agent(tool, tmp_path)

    messages = _call(agent, "bash", {"command": "curl https://example.com"}, tmp_path)

    assert tool.calls == []
    assert "not allowed" in messages[0]["content"]


def test_shared_execution_rewrites_allowed_python(tmp_path, shared_policy) -> None:
    tool = _FakeBashTool("bash")
    agent = _agent(tool, tmp_path)

    _call(agent, "bash", {"command": "python report.py"}, tmp_path)

    assert len(tool.calls) == 1
    assert tool.calls[0]["command"].startswith(sys.executable)


def test_shared_execution_fail_closed_for_a_directly_denied_tool(tmp_path, shared_policy) -> None:
    tool = _FakeBashTool("trading_place_order")
    agent = _agent(tool, tmp_path)

    messages = _call(agent, "trading_place_order", {}, tmp_path)

    assert tool.calls == []
    assert "disabled by the active tool policy" in messages[0]["content"]


def test_generic_off_allows_the_shared_bash_path_unchanged(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("VIBE_TRADING_BASH_POLICY", "off")
    reset_env_config()
    tool = _FakeBashTool("bash")
    agent = _agent(tool, tmp_path)

    _call(agent, "bash", {"command": "curl https://example.com"}, tmp_path)

    assert len(tool.calls) == 1
    assert tool.calls[0]["command"] == "curl https://example.com"


def test_generic_values_override_legacy_aliases(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CLI_BASH_POLICY", "off")
    monkeypatch.setenv("VIBE_TRADING_BASH_POLICY", "python-only")
    monkeypatch.setenv("VIBE_TRADING_DENY_TOOL_PREFIXES", "custom_")
    reset_env_config()

    assert bash_policy() == "python-only"
    assert policy_status() == {
        "deny_tool_prefixes": ["custom_"],
        "deny_tool_prefixes_source": "VIBE_TRADING_DENY_TOOL_PREFIXES",
        "bash_policy": "python-only",
        "bash_policy_source": "VIBE_TRADING_BASH_POLICY",
    }


def test_legacy_values_remain_the_fallback(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CLI_BASH_POLICY", "off")
    monkeypatch.setenv("CLAUDE_CLI_DENY_TOOL_PREFIXES", "legacy_")
    reset_env_config()

    assert policy_status()["deny_tool_prefixes"] == ["legacy_"]
    assert policy_status()["bash_policy"] == "off"


def test_invalid_generic_policy_names_the_generic_variable(monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_BASH_POLICY", "strict")
    reset_env_config()

    with pytest.raises(RuntimeError, match="VIBE_TRADING_BASH_POLICY"):
        bash_policy()


def test_provider_doctor_exposes_only_the_active_nonsecret_policy(monkeypatch) -> None:
    monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-test")
    monkeypatch.setenv("VIBE_TRADING_DENY_TOOL_PREFIXES", "custom_")
    monkeypatch.setenv("VIBE_TRADING_BASH_POLICY", "off")
    reset_env_config()

    diagnostics = provider_diagnostics()

    assert diagnostics["tool_policy"] == {
        "deny_tool_prefixes": ["custom_"],
        "deny_tool_prefixes_source": "VIBE_TRADING_DENY_TOOL_PREFIXES",
        "bash_policy": "off",
        "bash_policy_source": "VIBE_TRADING_BASH_POLICY",
    }
    assert get_env_config().llm.vibe_trading_deny_tool_prefixes == "custom_"


def test_unconfigured_non_claude_provider_keeps_its_previous_tool_surface():
    llm = _RecordingLLM()
    _chat(llm).chat([{"role": "user", "content": "x"}], tools=[_tool("trading_place_order")])
    assert [t["function"]["name"] for t in llm.bound_tools] == ["trading_place_order"]
    assert bash_policy() == "off"


def test_all_filtered_tools_do_not_bind_an_empty_schema(shared_policy):
    llm = _RecordingLLM()
    response = _chat(llm).chat([{"role": "user", "content": "x"}], tools=[_tool("trading_place_order")])
    assert response.content == "ok"
    assert llm.bound_tools is None


def test_direct_registry_execution_cannot_bypass_policy(shared_policy):
    tool = _FakeBashTool("trading_place_order")
    registry = ToolRegistry()
    registry.register(tool)
    result = json.loads(registry.execute(tool.name, {}))
    assert result["status"] == "error"
    assert tool.calls == []


def test_python_screening_is_idempotent_across_adapter_and_registry():
    first, reason = tool_policy.check_bash_command('python -c "print(1)"')
    assert reason is None
    second, reason = tool_policy.check_bash_command(first)
    assert reason is None
    assert second == first


def test_windows_python_paths_use_cmd_quoting(monkeypatch):
    patch_module_os(monkeypatch, tool_policy, name="nt")
    monkeypatch.setattr(tool_policy.sys, "executable", r"C:\Program Files\Python\python.exe")
    command, reason = tool_policy.check_bash_command('python -c "print(1)"')
    assert reason is None
    assert command.startswith('"C:\\Program Files\\Python\\python.exe" ')
