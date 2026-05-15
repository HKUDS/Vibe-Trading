"""Regression tests for AgentLoop terminal-state result dict (issue #114).

Before the fix, AgentLoop.run() returned a dict missing the `reason` field
on the cancelled and max-iter-failed branches even though state.json on
disk recorded a useful reason. SessionService then surfaced
'Execution failed: unknown' to the chat UI.

These tests exercise both terminal paths with a stubbed LLM so the loop
exits without hitting any real API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from src.agent.loop import AgentLoop


class _StubLLMResponse:
    """Minimal stand-in for ChatLLM's response object."""

    def __init__(self) -> None:
        self.content = ""
        self.tool_calls: list[Any] = []
        self.reasoning_content: str | None = None
        self.has_tool_calls = False


class _StubLLMNoFinal:
    """LLM stub that always returns an empty answer with no tool calls.

    Triggers the 'pipeline did not complete' branch on the first iteration
    because `final_content` stays empty and no `metrics.csv` is written.
    """

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
    ) -> _StubLLMResponse:
        return _StubLLMResponse()

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> _StubLLMResponse:
        return _StubLLMResponse()


class _StubLLMCancelMidStream:
    """LLM stub that cancels the loop from inside the LLM call.

    Mimics the user pressing the cancel button while waiting on the
    provider; the loop must surface 'cancelled by user' to the UI.
    """

    def __init__(self, agent_ref: "list[AgentLoop]") -> None:
        self._agent_ref = agent_ref

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
    ) -> _StubLLMResponse:
        # Set _cancelled on the bound agent so the next loop iteration check
        # picks it up.  We still need a valid response so the current
        # iteration completes cleanly.
        self._agent_ref[0]._cancelled = True
        return _StubLLMResponse()

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> _StubLLMResponse:
        return _StubLLMResponse()


def _build_agent(llm: Any, max_iter: int = 3, tmp_run_dir: Path | None = None) -> AgentLoop:
    """Build an AgentLoop with a real (but empty) registry and a stub LLM."""
    from src.tools import build_registry
    from src.memory.persistent import PersistentMemory

    pm = PersistentMemory()
    agent = AgentLoop(
        registry=build_registry(persistent_memory=pm, include_shell_tools=False),
        llm=llm,
        event_callback=None,
        max_iterations=max_iter,
        persistent_memory=pm,
    )
    if tmp_run_dir is not None:
        tmp_run_dir.mkdir(parents=True, exist_ok=True)
        agent.memory.run_dir = str(tmp_run_dir)
    return agent


def test_failed_terminal_returns_reason_iterations_and_max_iterations(
    tmp_path: Path,
) -> None:
    """When the loop exits without a final answer or metrics.csv, the
    returned dict must carry `reason`, `iterations`, and `max_iterations`
    so SessionService can render an actionable error message."""
    agent = _build_agent(_StubLLMNoFinal(), max_iter=3, tmp_run_dir=tmp_path / "run")

    result = agent.run(user_message="anything")

    assert result["status"] == "failed"
    assert result["reason"] == "reached max iterations (3) without final answer"
    assert result["iterations"] >= 1
    assert result["max_iterations"] == 3


def test_cancelled_terminal_returns_reason(tmp_path: Path) -> None:
    """Cancelled-by-user runs must also surface a meaningful reason."""
    agent_ref: list[AgentLoop] = []
    agent = _build_agent(
        _StubLLMCancelMidStream(agent_ref),
        max_iter=3,
        tmp_run_dir=tmp_path / "run",
    )
    agent_ref.append(agent)

    result = agent.run(user_message="anything")

    assert result["status"] == "cancelled"
    assert result["reason"] == "cancelled by user"
    assert result["max_iterations"] == 3


def test_session_service_renders_meaningful_error_from_result(tmp_path: Path) -> None:
    """End-to-end guard for the original UI symptom in #114: with the new
    `reason` field populated, `result.get('reason', 'unknown')` returns the
    meaningful string SessionService passes to attempt.mark_failed."""
    agent = _build_agent(_StubLLMNoFinal(), max_iter=2, tmp_run_dir=tmp_path / "run")

    result = agent.run(user_message="anything")
    ui_error = result.get("reason", "unknown")

    assert ui_error != "unknown"
    assert "max iterations" in ui_error
    assert "2" in ui_error
