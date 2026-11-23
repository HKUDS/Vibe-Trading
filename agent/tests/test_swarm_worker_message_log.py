"""A worker's terminal summary and message log are persisted together.

``messages.json`` is the only record of the arguments a model asked a tool
for: the assistant message carries ``function.arguments`` verbatim, while the
event stream redacts ``run_dir`` from the argument preview. A terminal path
that reports a summary must also write the log, so a completed run, a token
limit, a content-filter trip and an output-contract rejection all leave the
same two files.
"""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import json
from collections.abc import Callable
from pathlib import Path

import pytest

import src.swarm.runtime as runtime_mod
import src.swarm.node as worker_mod
from src.agent.tools import BaseTool, ToolRegistry
from src.kernel.contracts import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmTask
from src.swarm.presets import build_run_from_preset
from src.swarm.store import SwarmStore
from src.tools import web_reader_tool
from src.session.thread import ThreadLog
from src.swarm.artifacts import agent_artifact_dir, node_thread
from src.swarm.node import run_node


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

    def stream_chat(self, messages, tools=None, timeout=None, on_text_chunk=None, on_waiting_chunk=None, **_callbacks):
        return self._responses.pop(0)

    def close(self) -> None:
        """No-op: the scripted stub owns no HTTP client."""


class _ContentFilteredLLM:
    """Every response is blocked, so the worker trips its circuit breaker."""

    def __init__(self) -> None:
        self._remaining = 20

    def stream_chat(self, messages, tools=None, timeout=None, on_text_chunk=None, on_waiting_chunk=None, **_callbacks):
        self._remaining -= 1
        if self._remaining >= 0:
            return LLMResponse(content="", content_filter_triggered=True)
        return LLMResponse(content="unreachable", tool_calls=[])

    def close(self) -> None:
        """No-op: the scripted stub owns no HTTP client."""


class _AnswersWithoutToolCallsLLM:
    """A final answer and nothing else, for a data agent that never probed."""

    def stream_chat(self, messages, tools=None, timeout=None, on_text_chunk=None, on_waiting_chunk=None, **_callbacks):
        return LLMResponse(
            content="The market looks range-bound, so no further analysis is needed.",
            tool_calls=[],
            finish_reason="stop",
        )

    def close(self) -> None:
        """No-op: the scripted stub owns no HTTP client."""


def _run_node_to_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    llm_factory: Callable[[], object] | None = None,
    max_iterations: int = 3,
):
    """Run the real worker on a scripted model until it stops."""
    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(_ProbeTool())
    monkeypatch.setattr(
        worker_mod, "build_swarm_registry", lambda *args, **kwargs: registry
    )
    monkeypatch.setattr(
        worker_mod, "ChatLLM", lambda *args, **kwargs: (llm_factory or _ScriptedLLM)()
    )
    return run_node(
        policy=ToolPolicy.from_config(get_env_config()),
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


@pytest.mark.parametrize("readonly,initial_status", [(True, "ok"), (True, "error"), (False, "ok")])
def test_worker_reuses_only_successful_identical_reads(tmp_path, monkeypatch, readonly, initial_status):
    invocations = []

    def execute(self, **kwargs):
        invocations.append(kwargs)
        status = initial_status if len(invocations) == 1 else "ok"
        return json.dumps({"status": status, "data": [len(invocations)]})

    monkeypatch.setattr(_ProbeTool, "is_readonly", readonly)
    monkeypatch.setattr(_ProbeTool, "execute", execute)
    model = _ScriptedLLM()
    arguments = model._responses[0].tool_calls[0].arguments
    arguments["subject"] = arguments.pop("symbol")
    model._responses[0].tool_calls.extend([
        ToolCallRequest("call-2", "market_probe", {"window": 7, "subject": "BTC-USDT"}),
        ToolCallRequest("call-3", "market_probe", {"window": 8, "subject": "BTC-USDT"}),
    ])
    result = _run_node_to_terminal(tmp_path, monkeypatch, llm_factory=lambda: model)
    assert result.status == "completed", result.error
    artifact_dir = agent_artifact_dir(tmp_path, "analyst", "task")
    messages = ThreadLog(node_thread(tmp_path, "analyst", "task")).read()
    results = [json.loads(message.get("content")) for message in messages if message.type == "tool_result"]
    assert len(results) == 3
    if readonly and initial_status == "ok":
        assert len(invocations) == 2
        assert results[1] == {"status": "ok", "data": [1], "_vibe_repeat": True}
    else:
        assert len(invocations) == 3
        assert results[1] == {"status": "ok", "data": [2]}
    assert invocations[-1]["window"] == 8


@pytest.mark.parametrize("retry_node", [False, True])
def test_credit_research_rate_node_reuses_read_url_result(tmp_path, monkeypatch, retry_node):
    url = "https://example.com/central-bank-calendar"
    result_json = {"status": "ok", "url": url, "content": "Next announcement: November 23."}
    fetches = []

    def read(url, *, no_cache):
        fetches.append((url, no_cache))
        return json.dumps(result_json)

    def request(call_id):
        return LLMResponse(
            tool_calls=[ToolCallRequest(call_id, "read_url", {"url": url})],
            finish_reason="tool_calls",
        )

    model = _ScriptedLLM()
    if retry_node:
        first_model = _ScriptedLLM()
        first_model._responses[:] = [request("first")]
        model._responses[:1] = [request("repeat")]
        models = iter([first_model, model])
    else:
        model._responses[:1] = [request("first"), request("repeat")]
        models = iter([model])
    monkeypatch.setattr(web_reader_tool, "read_url", read)
    monkeypatch.setattr(worker_mod, "ChatLLM", lambda *args, **kwargs: next(models))
    preset = build_run_from_preset("credit_research_team", {"target": "AAPL", "market": "US"})
    task = next(task for task in preset.tasks if task.id == "task-rate")
    agent = next(agent for agent in preset.agents if agent.id == task.agent_id)
    policy = ToolPolicy.from_config(get_env_config())
    kwargs = dict(
        agent_spec=agent, task=task, upstream_summaries={},
        user_vars=preset.user_vars, run_dir=tmp_path,
    )
    if retry_node:
        events = []
        host = runtime_mod.SwarmRuntime(store=SwarmStore(tmp_path), policy=policy)
        monkeypatch.setattr(runtime_mod, "_worker_retry_delay_s", lambda _: 0)
        result = host._run_node_with_retries(
            **kwargs, event_callback=events.append, run_id=preset.id,
        )
        assert [event.type for event in events if event.type in {"task_retry", "worker_resumed"}] == [
            "task_retry", "worker_resumed",
        ]
    else:
        result = run_node(policy=policy, **kwargs)
    assert result.status == "completed", result.error
    assert fetches == [(url, False)]
    artifact_dir = agent_artifact_dir(tmp_path, agent.id, task.id)
    messages = ThreadLog(node_thread(tmp_path, agent.id, task.id)).read()
    results = [json.loads(message.get("content")) for message in messages if message.type == "tool_result"]
    assert results == [result_json, {**result_json, "_vibe_repeat": True}]


def test_completed_run_persists_the_message_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker that completes must leave a message log, not only a summary."""
    result = _run_node_to_terminal(tmp_path, monkeypatch)
    artifact_dir = agent_artifact_dir(tmp_path, "analyst", "task")

    assert result.status == "completed", result.error
    assert not (artifact_dir / "summary.md").exists()
    assert not (artifact_dir / "messages.json").exists()
    assert ThreadLog(node_thread(tmp_path, "analyst", "task")).read()


def test_token_limit_run_persists_the_message_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker stopped by the token limit must leave a message log too."""
    monkeypatch.setattr(worker_mod.NodeContext, "tokens", lambda *_: float("inf"))
    result = _run_node_to_terminal(tmp_path, monkeypatch)
    artifact_dir = agent_artifact_dir(tmp_path, "analyst", "task")

    assert result.status == "token_limit"
    assert not (artifact_dir / "summary.md").exists()
    assert not (artifact_dir / "messages.json").exists()
    assert ThreadLog(node_thread(tmp_path, "analyst", "task")).read()


def test_content_filter_circuit_breaker_persists_the_message_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker failed by the content-filter breaker must leave a log too."""
    result = _run_node_to_terminal(
        tmp_path,
        monkeypatch,
        llm_factory=_ContentFilteredLLM,
        max_iterations=20,
    )
    artifact_dir = agent_artifact_dir(tmp_path, "analyst", "task")

    assert result.status == "failed"
    assert "circuit_breaker" in (result.error or "")
    assert not (artifact_dir / "summary.md").exists()
    assert not (artifact_dir / "messages.json").exists()
    assert ThreadLog(node_thread(tmp_path, "analyst", "task")).read()


def test_no_tool_answer_persists_the_message_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A data agent that answers without calling a tool must leave a log too."""
    result = _run_node_to_terminal(
        tmp_path, monkeypatch, llm_factory=_AnswersWithoutToolCallsLLM
    )
    artifact_dir = agent_artifact_dir(tmp_path, "analyst", "task")

    assert result.status == "completed", result.error
    assert result.error is None
    assert not (artifact_dir / "summary.md").exists()
    assert not (artifact_dir / "messages.json").exists()
    assert ThreadLog(node_thread(tmp_path, "analyst", "task")).read()


def test_message_log_carries_the_tool_call_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The log must hold what the model asked the tool for, not only roles."""
    _run_node_to_terminal(tmp_path, monkeypatch)
    log_path = node_thread(tmp_path, "analyst", "task")
    messages = ThreadLog(log_path).read()

    assert any(
        '"symbol": "BTC-USDT"' in call["function"]["arguments"]
        for message in messages
        if message.type == "assistant"
        for call in (message.get("tool_calls") or [])
    )
