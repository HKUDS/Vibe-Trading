"""Regression tests for DSML textual tool calls in the ReAct loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from src.agent.loop import AgentLoop
from src.agent.progress import emit_progress
from src.agent.tools import BaseTool, ToolRegistry
from src.memory.persistent import PersistentMemory
from src.providers.chat import ChatLLM, LLMResponse, ToolCallRequest


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
        "src.agent.tool_lifecycle.HeartbeatTimer", _ImmediateHeartbeatTimer
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

def test_agent_loop_never_releases_tool_call_syntax_as_a_final_answer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Forced-text final answers containing tool-call DSL are not released raw.

    On the last iteration tools are withheld to guarantee a plain-text answer,
    but a model can still emit its native tool-call markup as prose (plain or
    fullwidth-vbar mojibake). That markup is not an answer: the loop must
    retry when budget remains, otherwise release a deterministic message and
    mark the run degraded instead of leaking ``<...tool_calls>`` to the user.
    """
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
        "src.agent.tool_lifecycle.HeartbeatTimer", _ImmediateHeartbeatTimer
    )
    # The fullwidth-vbar (U+FF5C) form is what the real failure looked like; the
    # streaming DSML parser does not recognize it, so it arrives as text.
    garbage = "<││DSML││tool_calls><││invoke name=\"trading_quote\">"
    registry = ToolRegistry()
    events: list[tuple[str, dict[str, Any]]] = []
    agent = AgentLoop(
        registry=registry,
        llm=_chat_llm(_ScriptedStreamingLLM([garbage, garbage])),
        event_callback=lambda event_type, payload: events.append((event_type, payload)),
        max_iterations=1,  # the single iteration is the forced-text last one
        persistent_memory=PersistentMemory(memory_dir=tmp_path / "memory"),
    )
    agent.memory.run_dir = str(tmp_path / "run")

    result = agent.run("hello")

    assert result["status"] == "success"
    assert result.get("degraded") is True
    assert result["iterations"] == 2
    assert "tool-call syntax" in result["content"]
    assert "<" not in result["content"]
    assert not any(
        event_type == "answer" and "<" in str(payload)
        for event_type, payload in events
    )


def test_closing_dsml_tags_alone_are_tool_call_syntax() -> None:
    """A DeepSeek draft once ended in closing tags only, inside its figures block;
    the opening-tag pattern missed them and the gate got three unreadable lines."""
    from src.agent.loop import _looks_like_tool_call_syntax

    tail = "\n".join(
        [
            "```figures",
            "0.3897 | observed | weight | rp",
            "</｜｜DSML｜｜parameter>",
            "</｜｜DSML｜｜invoke>",
            "</｜｜DSML｜｜tool_calls>",
        ]
    )

    assert _looks_like_tool_call_syntax("Report.\n\n" + tail)
    assert _looks_like_tool_call_syntax("done </||DSML||invoke>")
    assert not _looks_like_tool_call_syntax("| 标的 | 权重 |\n|---|---|\n| 000001.SZ | 38.97% |")


@pytest.mark.parametrize("max_iterations", [1, 3])
def test_final_tool_syntax_gets_one_text_only_retry(
    tmp_path: Path, max_iterations: int
) -> None:
    """A withheld final answer can be re-emitted after research hits its cap."""
    dsml = (
        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="echo_probe">'
        '<｜｜DSML｜｜parameter name="marker" string="true">ready</｜｜DSML｜｜parameter>'
        "</｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>"
    )
    garbage = '<││DSML││tool_calls><││invoke name="echo_probe">'
    responses = [dsml] * (max_iterations - 1) + [garbage, "The report is ready."]
    registry = ToolRegistry()
    registry.register(_EchoProbeTool())
    events: list[tuple[str, dict[str, Any]]] = []
    agent = AgentLoop(
        registry=registry,
        llm=_chat_llm(_ScriptedStreamingLLM(responses)),
        event_callback=lambda kind, payload: events.append((kind, payload)),
        max_iterations=max_iterations,
        persistent_memory=PersistentMemory(memory_dir=tmp_path / "memory"),
    )
    agent.memory.run_dir = str(tmp_path / "run")

    result = agent.run("use the probe and report")

    assert result["status"] == "success"
    assert result["content"] == "The report is ready."
    assert result["iterations"] == max_iterations + 1
    assert not result.get("degraded")
    assert sum(kind == "tool_result" for kind, _ in events) == max_iterations - 1
    assert not responses
    shown = ""
    for kind, payload in events:
        if kind == "stream_reset":
            shown = ""
        elif kind == "text_delta":
            shown += payload["delta"]
    assert shown == "The report is ready."


class _AnswerRetryLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = responses
        self.offered_tools: list[list[dict[str, Any]] | None] = []

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.offered_tools.append(tools)
        response = self.responses.pop(0)
        if on_text_chunk and response.content:
            on_text_chunk(response.content)
        return response


def test_final_answer_retry_cannot_execute_unoffered_tools(tmp_path: Path) -> None:
    """A provider ignoring text-only mode cannot reopen tool execution."""
    garbage = '<││DSML││tool_calls><││invoke name="echo_probe">'
    llm = _AnswerRetryLLM(
        [
            LLMResponse(content=garbage),
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="retry-call",
                        name="echo_probe",
                        arguments={"marker": "unexpected"},
                    )
                ],
            ),
        ]
    )
    registry = ToolRegistry()
    registry.register(_EchoProbeTool())
    events: list[tuple[str, dict[str, Any]]] = []
    agent = AgentLoop(
        registry=registry,
        llm=llm,
        event_callback=lambda kind, payload: events.append((kind, payload)),
        max_iterations=1,
        persistent_memory=PersistentMemory(memory_dir=tmp_path / "memory"),
    )
    agent.memory.run_dir = str(tmp_path / "run")

    result = agent.run("report")

    assert not any(kind in {"tool_call", "tool_result"} for kind, _ in events)
    assert llm.offered_tools == [None, None]
    assert result["iterations"] == 2
    assert result.get("degraded") is True
    assert "tool-call syntax" in result["content"]


@pytest.mark.parametrize("token_budget, expected_calls", [(10, 1), (100, 2)])
def test_answer_retry_obeys_goal_budget_and_accounts_usage(
    tmp_path: Path, monkeypatch, token_budget: int, expected_calls: int
) -> None:
    from src.goal import GoalStore

    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    monkeypatch.setattr("src.agent.loop.SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr("src.agent.tuning.GOAL_MAX_CONTINUATIONS", 1, raising=False)
    store = GoalStore()
    goal = store.replace_goal(
        session_id="retry-session",
        objective="Write a report.",
        criteria=["Deliver the report"],
        token_budget=token_budget,
    )
    garbage = '<││DSML││tool_calls><││invoke name="echo_probe">'
    llm = _AnswerRetryLLM(
        [
            LLMResponse(content=garbage, usage_metadata={"total_tokens": 15}),
            LLMResponse(
                content="The report is ready.", usage_metadata={"total_tokens": 20}
            ),
        ]
    )
    agent = AgentLoop(
        registry=ToolRegistry(),
        llm=llm,
        max_iterations=1,
        persistent_memory=PersistentMemory(memory_dir=tmp_path / "memory"),
    )
    agent.memory.run_dir = str(tmp_path / "run")

    result = agent.run("Write a report.", session_id="retry-session")

    assert len(llm.offered_tools) == expected_calls
    updated = store.get_goal(goal.goal_id)
    assert updated.tokens_used == (15 if expected_calls == 1 else 35)
    assert updated.turns_used == 1
    usage = json.loads((Path(result["run_dir"]) / "llm_usage.json").read_text())
    assert usage["totals"]["calls"] == expected_calls
    assert usage["totals"]["total_tokens"] == updated.tokens_used
    if expected_calls == 1:
        assert "budget" in result["reason"]
        assert not result["content"]
    else:
        assert result["content"] == "The report is ready."
        assert [row["iter"] for row in usage["per_iteration"]] == [1, 2]


def test_cancel_after_rejected_answer_prevents_retry(tmp_path: Path) -> None:
    garbage = '<││DSML││tool_calls><││invoke name="echo_probe">'
    llm = _AnswerRetryLLM([LLMResponse(content=garbage)])
    agent = AgentLoop(
        registry=ToolRegistry(),
        llm=llm,
        max_iterations=1,
        persistent_memory=PersistentMemory(memory_dir=tmp_path / "memory"),
        event_callback=lambda kind, payload: (
            agent.cancel() if kind == "stream_reset" else None
        ),
    )
    agent.memory.run_dir = str(tmp_path / "run")

    result = agent.run("Write a report.")

    assert result["status"] == "cancelled"
    assert len(llm.offered_tools) == 1


def test_retried_answer_still_passes_grounding(tmp_path: Path) -> None:
    garbage = '<││DSML││tool_calls><││invoke name="echo_probe">'
    llm = _AnswerRetryLLM(
        [
            LLMResponse(content=garbage),
            LLMResponse(content="AAPL is trading at $999.00."),
        ]
    )
    agent = AgentLoop(
        registry=ToolRegistry(),
        llm=llm,
        max_iterations=1,
        persistent_memory=PersistentMemory(memory_dir=tmp_path / "memory"),
    )
    agent.memory.run_dir = str(tmp_path / "run")

    result = agent.run("What is the AAPL stock price?")

    assert result.get("degraded") is True
    assert "$999.00" not in result["content"]
    assert llm.offered_tools == [None, None]


def test_answer_retry_blocks_calls_after_grounding_correction(tmp_path: Path) -> None:
    garbage = '<││DSML││tool_calls><││invoke name="echo_probe">'
    llm = _AnswerRetryLLM(
        [
            LLMResponse(content="The return was 9.99%."),
            LLMResponse(content=garbage),
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(id="retry", name="echo_probe", arguments={})
                ],
            ),
        ]
    )
    registry = ToolRegistry()
    registry.register(_EchoProbeTool())
    events: list[tuple[str, dict[str, Any]]] = []
    agent = AgentLoop(
        registry=registry,
        llm=llm,
        max_iterations=2,
        event_callback=lambda kind, payload: events.append((kind, payload)),
        persistent_memory=PersistentMemory(memory_dir=tmp_path / "memory"),
    )
    agent.memory.run_dir = str(tmp_path / "run")

    result = agent.run("Summarize the returns.")

    assert result["iterations"] == 3
    assert result.get("degraded") is True
    assert "tool-call syntax" in result["content"]
    assert not any(kind in {"tool_call", "tool_result"} for kind, _ in events)
