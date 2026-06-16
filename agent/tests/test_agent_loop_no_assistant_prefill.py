"""Regression test: agent loop must not end messages with assistant prefill.

Claude Opus 4.8+ (and other new Anthropic models) reject API requests
when the conversation ends with an assistant-role message, because the
API treats it as an "assistant prefill" which these models no longer
support.  Two code paths in AgentLoop used to emit such messages:
background notification acknowledgments and auto-compact handoff notes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agent.loop import AgentLoop


class _StubLLM:
    """ChatLLM stub that returns text then an answer after one tool call."""

    def __init__(self) -> None:
        self.model_name = "claude-opus-4-8-20250219"

    _call_count = 0

    class _Response:
        content: str = "Here is the analysis of AAPL stock."
        tool_calls: list[Any] = []
        reasoning_content: str | None = None
        has_tool_calls = False

    class _ToolResponse(_Response):
        has_tool_calls = True
        content = "Here is the analysis of AAPL stock."

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: Any = None,
        on_text_chunk: Any = None,
        on_reasoning_chunk: Any = None,
    ) -> Any:
        messages = [m for m in messages]
        _StubLLM._call_count += 1

        for msg in reversed(messages):
            if msg.get("role") in ("user", "system", "tool"):
                break
            if msg.get("role") == "assistant":
                raise AssertionError(
                    f"Messages should not end with assistant role "
                    f"(call #{_StubLLM._call_count}): {msg}"
                )

        return self._Response()

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> Any:
        return self._Response()


def _build_agent(llm: Any, max_iter: int = 3, tmp_run_dir: Path | None = None) -> AgentLoop:
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


def test_agent_run_messages_never_end_with_assistant(tmp_path: Path) -> None:
    """A simple run() should never send a trailing assistant message to the LLM."""
    agent = _build_agent(
        _StubLLM(),
        max_iter=5,
        tmp_run_dir=tmp_path / "run",
    )
    result = agent.run("Analyze AAPL stock for 2024")
    assert result["status"] == "success"
    assert _StubLLM._call_count >= 1
