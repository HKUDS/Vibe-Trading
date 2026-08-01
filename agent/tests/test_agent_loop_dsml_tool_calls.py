"""Regression tests for DSML textual tool calls in the ReAct loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agent.loop import AgentLoop
from src.agent.progress import emit_progress
from src.agent.tools import BaseTool, ToolRegistry
from src.memory.persistent import PersistentMemory
from src.providers.chat import ChatLLM


class _Chunk:
    """Minimal LangChain AIMessageChunk stand-in."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.tool_calls: list[dict[str, Any]] = []
        self.additional_kwargs: dict[str, Any] = {}
        self.response_metadata = {"finish_reason": "stop"}
        self.usage_metadata = None

    def __add__(self, other: "_Chunk") -> "_Chunk":
        return _Chunk(f"{self.content}{other.content}")


class _ScriptedStreamingLLM:
    """Return one scripted response per stream_chat call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses

    def bind_tools(self, tools: list[dict[str, Any]]) -> "_ScriptedStreamingLLM":
        return self

    def stream(self, messages: list[dict[str, Any]], config: dict[str, Any] | None = None):
        yield _Chunk(self._responses.pop(0))


class _EchoProbeTool(BaseTool):
    """Safe test tool proving DSML calls reach the normal tool executor."""

    name = "echo_probe"
    description = "Echo a marker for DSML tool-call regression tests."
    parameters = {
        "type": "object",
        "properties": {"marker": {"type": "string"}},
        "required": ["marker"],
    }
    repeatable = True
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        emit_progress("echoing", current=1, total=1)
        return json.dumps({"status": "ok", "marker": kwargs.get("marker")})


def _chat_llm(fake_llm: _ScriptedStreamingLLM) -> ChatLLM:
    client = ChatLLM.__new__(ChatLLM)
    client.model_name = "deepseek-v4-pro"
    client._llm = fake_llm
    return client


def test_agent_loop_executes_dsml_textual_tool_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A pure DSML response must execute as a tool call instead of final text."""
    class _ImmediateHeartbeatTimer:
        def __init__(self, tool_name: str, interval: float, emit) -> None:
            del interval
            self._tool_name = tool_name
            self._emit = emit

        def __enter__(self):
            self._emit({"tool": self._tool_name, "elapsed_s": 0.01})
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(
        "src.agent.loop.HeartbeatTimer", _ImmediateHeartbeatTimer
    )
    dsml = (
        '<｜｜DSML｜｜tool_calls>'
        '<｜｜DSML｜｜invoke name="echo_probe">'
        '<｜｜DSML｜｜parameter name="marker" string="true">ran-dsml</｜｜DSML｜｜parameter>'
        "</｜｜DSML｜｜invoke>"
        "</｜｜DSML｜｜tool_calls>"
    )
    registry = ToolRegistry()
    registry.register(_EchoProbeTool())
    memory = PersistentMemory(memory_dir=tmp_path / "memory")
    events: list[tuple[str, dict[str, Any]]] = []
    agent = AgentLoop(
        registry=registry,
        llm=_chat_llm(_ScriptedStreamingLLM([dsml, "final answer"])),
        event_callback=lambda event_type, payload: events.append((event_type, payload)),
        max_iterations=2,
        persistent_memory=memory,
    )
    agent.memory.run_dir = str(tmp_path / "run")

    result = agent.run("use the probe")

    assert result["status"] == "success"
    assert result["content"] == "final answer"
    tool_events = {
        event_type: payload
        for event_type, payload in events
        if event_type
        in {"tool_call", "tool_progress", "tool_heartbeat", "tool_result"}
    }
    assert set(tool_events) == {
        "tool_call",
        "tool_progress",
        "tool_heartbeat",
        "tool_result",
    }
    assert {
        payload["call_id"] for payload in tool_events.values()
    } == {"dsml_call_1"}
    assert {
        payload["tool"] for payload in tool_events.values()
    } == {"echo_probe"}
