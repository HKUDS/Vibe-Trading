"""A worker's terminal summary and message log are persisted together.

``messages.json`` is the only record of the arguments a model asked a tool
for: the assistant message carries ``function.arguments`` verbatim, while the
event stream redacts ``run_dir`` from the argument preview. A terminal path
that reports a summary must also write the log, so a completed run, a token
limit, a content-filter trip and an output-contract rejection all leave the
same two files.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import src.swarm.worker as worker_mod
from src.agent.tools import BaseTool, ToolRegistry
from src.providers.chat import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmTask
from src.swarm.worker import agent_artifact_dir, run_worker


class _ProbeTool(BaseTool):
    """Return one canned result so the worker reaches a terminal state."""

    name = "market_probe"
    description = "Return a canned market result."
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> str:
        return '{"status": "ok", "data": [1]}'


class _ScriptedLLM:
    """One tool call carrying arguments, then a final answer with no tools."""

    def __init__(self) -> None:
        self._responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call-1",
                        name="market_probe",
                        arguments={"symbol": "BTC-USDT", "window": 7},
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="Completed the requested market analysis with a clear conclusion.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]

    def stream_chat(self, messages, tools=None, timeout=None, on_text_chunk=None):
        return self._responses.pop(0)

    def close(self) -> None:
        """No-op: the scripted stub owns no HTTP client."""


class _ContentFilteredLLM:
    """Every response is blocked, so the worker trips its circuit breaker."""

    def __init__(self) -> None:
        self._remaining = 20

    def stream_chat(self, messages, tools=None, timeout=None, on_text_chunk=None):
        self._remaining -= 1
        if self._remaining >= 0:
            return LLMResponse(content="", content_filter_triggered=True)
        return LLMResponse(content="unreachable", tool_calls=[])

    def close(self) -> None:
        """No-op: the scripted stub owns no HTTP client."""


class _AnswersWithoutToolCallsLLM:
    """A final answer and nothing else, for a data agent that never probed."""

    def stream_chat(self, messages, tools=None, timeout=None, on_text_chunk=None):
        return LLMResponse(
            content="The market looks range-bound, so no further analysis is needed.",
            tool_calls=[],
            finish_reason="stop",
        )

    def close(self) -> None:
        """No-op: the scripted stub owns no HTTP client."""


def _run_worker_to_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    llm_factory: Callable[[], object] | None = None,
    max_iterations: int = 3,
):
    """Run the real worker on a scripted model until it stops."""
    monkeypatch.setattr(worker_mod, "_STREAM_RETRY_DELAY_S", 0.0)
    registry = ToolRegistry()
    registry.register(_ProbeTool())
    monkeypatch.setattr(
        worker_mod, "build_swarm_registry", lambda *args, **kwargs: registry
    )
    monkeypatch.setattr(
        worker_mod, "ChatLLM", lambda *args, **kwargs: (llm_factory or _ScriptedLLM)()
    )
    return run_worker(
        agent_spec=SwarmAgentSpec(
            id="analyst",
            role="Analyst",
            system_prompt="Analyse the result.",
            tools=["market_probe"],
            max_iterations=max_iterations,
        ),
        task=SwarmTask(
            id="task", agent_id="analyst", prompt_template="Probe the market."
        ),
        upstream_summaries={},
        user_vars={},
        run_dir=tmp_path,
        event_callback=lambda event: None,
    )


def test_completed_run_persists_the_message_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker that completes must leave a message log, not only a summary."""
    result = _run_worker_to_terminal(tmp_path, monkeypatch)
    artifact_dir = agent_artifact_dir(tmp_path, "analyst")

    assert result.status == "completed", result.error
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "messages.json").is_file()


def test_token_limit_run_persists_the_message_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker stopped by the token limit must leave a message log too."""
    monkeypatch.setattr(worker_mod, "_MAX_TOKEN_ESTIMATE", 0)
    result = _run_worker_to_terminal(tmp_path, monkeypatch)
    artifact_dir = agent_artifact_dir(tmp_path, "analyst")

    assert result.status == "token_limit"
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "messages.json").is_file()


def test_content_filter_circuit_breaker_persists_the_message_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker failed by the content-filter breaker must leave a log too."""
    result = _run_worker_to_terminal(
        tmp_path,
        monkeypatch,
        llm_factory=_ContentFilteredLLM,
        max_iterations=20,
    )
    artifact_dir = agent_artifact_dir(tmp_path, "analyst")

    assert result.status == "failed"
    assert "circuit_breaker" in (result.error or "")
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "messages.json").is_file()


def test_incomplete_run_persists_the_message_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A data agent that answers without calling a tool must leave a log too."""
    result = _run_worker_to_terminal(
        tmp_path, monkeypatch, llm_factory=_AnswersWithoutToolCallsLLM
    )
    artifact_dir = agent_artifact_dir(tmp_path, "analyst")

    assert result.status == "incomplete", result.error
    assert "no tool calls" in (result.error or "")
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "messages.json").is_file()


def test_message_log_carries_the_tool_call_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The log must hold what the model asked the tool for, not only roles."""
    _run_worker_to_terminal(tmp_path, monkeypatch)
    log_path = agent_artifact_dir(tmp_path, "analyst") / "messages.json"
    messages = json.loads(log_path.read_text(encoding="utf-8"))

    assert any(
        '"symbol": "BTC-USDT"' in call["function"]["arguments"]
        for message in messages
        if message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
    )
