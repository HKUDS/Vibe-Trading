"""Worker-side half of cooperative swarm cancellation.

``test_swarm_cancel_mid_flight_worker.py`` proves the runtime threads
``cancel_event`` from ``cancel_run()`` into ``run_worker``; this file proves
what ``run_worker`` does with it once it arrives:

* set before an iteration starts → no LLM call is made, status ``cancelled``;
* set while the stream is in flight → that turn's tool calls are never
  dispatched, status ``cancelled`` (a control run shows the same response
  *does* dispatch its tool when nothing is cancelled);
* the event is handed to ``ChatLLM.stream_chat`` as ``should_cancel`` — the
  same predicate ``AgentLoop`` passes — so the provider stream itself stops
  early instead of running to its natural end.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

from src.providers.chat import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmTask, WorkerResult
import src.swarm.worker as worker_mod
from src.swarm.worker import run_worker

_TOOL_DEF = {
    "type": "function",
    "function": {"name": "noop_tool", "description": "no-op", "parameters": {"type": "object", "properties": {}}},
}


class _Registry:
    """Registry stand-in exposing one tool and recording every dispatch."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def get_definitions(self) -> list[dict]:
        """Return the single scripted tool definition."""
        return [_TOOL_DEF]

    def get(self, name: str):
        """Local-only registry: no MCPRemoteTool, so no remote metadata."""
        return None

    def execute(self, name: str, args: dict) -> str:
        """Record the dispatch and return a benign JSON envelope."""
        self.executed.append(name)
        return '{"ok": true, "data": {}}'


class _ScriptedLLM:
    """``stream_chat`` stub that records its kwargs and can flip the cancel
    flag while "streaming", the way ``should_cancel`` would fire mid-stream."""

    def __init__(
        self,
        response: LLMResponse,
        cancel_event: threading.Event | None = None,
        set_on_stream: bool = False,
    ) -> None:
        self._response = response
        self._cancel_event = cancel_event
        self._set_on_stream = set_on_stream
        self.calls = 0
        self.should_cancel_seen: list[object] = []

    def __call__(self, *args, **kwargs) -> "_ScriptedLLM":
        """Support ``ChatLLM(model_name=...)`` constructor-style patching."""
        return self

    def close(self) -> None:
        """No-op: the stub owns no HTTP client."""
        return None

    def stream_chat(self, messages, tools=None, on_text_chunk=None, timeout=None, should_cancel=None, on_waiting_chunk=None):
        """Return the scripted response, optionally cancelling "mid-stream"."""
        self.calls += 1
        self.should_cancel_seen.append(should_cancel)
        if self._set_on_stream and self._cancel_event is not None:
            self._cancel_event.set()
        return self._response


def _tool_call_response() -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[ToolCallRequest(id="c1", name="noop_tool", arguments={})],
        finish_reason="tool_calls",
    )


def _run(tmp_path: Path, llm: _ScriptedLLM, registry: _Registry, cancel_event: threading.Event | None):
    """Run one tool-enabled worker against the scripted LLM and registry."""
    agent = SwarmAgentSpec(
        id="analyst",
        role="Analyst",
        system_prompt="You analyse.",
        tools=["noop_tool"],
        skills=[],
        max_iterations=2,
        timeout_seconds=60,
    )
    task = SwarmTask(id="t1", agent_id="analyst", prompt_template="Do the thing.")
    events: list[str] = []
    with (
        patch.object(worker_mod, "build_swarm_registry", lambda *a, **k: registry),
        patch.object(worker_mod, "ChatLLM", llm),
    ):
        result = run_worker(
            agent_spec=agent,
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=tmp_path,
            event_callback=lambda ev: events.append(ev.type),
            cancel_event=cancel_event,
        )
    return result, events


def test_cancel_set_before_first_iteration_makes_no_llm_call(tmp_path):
    cancel_event = threading.Event()
    cancel_event.set()
    llm = _ScriptedLLM(_tool_call_response())
    registry = _Registry()

    result, events = _run(tmp_path, llm, registry, cancel_event)

    assert isinstance(result, WorkerResult)
    assert result.status == "cancelled"
    assert llm.calls == 0, "a cancel signalled before the iteration must not start an LLM call"
    assert registry.executed == []
    assert "worker_cancelled" in events
    assert result.summary == ""  # cancellation is status, not invented research


def test_cancel_during_stream_skips_that_turns_tool_calls(tmp_path):
    cancel_event = threading.Event()
    llm = _ScriptedLLM(_tool_call_response(), cancel_event=cancel_event, set_on_stream=True)
    registry = _Registry()

    result, events = _run(tmp_path, llm, registry, cancel_event)

    assert result.status == "cancelled"
    assert llm.calls == 1
    assert registry.executed == [], (
        "tool calls from a turn whose stream was cancelled must not be dispatched, "
        f"got {registry.executed}"
    )
    assert "worker_cancelled" in events
    assert "tool_call" not in events


def test_same_response_dispatches_its_tool_when_nothing_is_cancelled(tmp_path):
    """Control for the test above: the scripted tool-call response really does
    reach the registry when no cancellation fires, so the empty ``executed``
    list there is the cancel check at work, not a stub that never dispatches."""
    llm = _ScriptedLLM(_tool_call_response())
    registry = _Registry()

    result, events = _run(tmp_path, llm, registry, cancel_event=None)

    assert result.status != "cancelled"
    assert registry.executed == ["noop_tool", "noop_tool"], registry.executed
    assert "tool_call" in events
    assert "worker_cancelled" not in events


def test_cancel_event_is_forwarded_to_stream_chat_as_should_cancel(tmp_path):
    cancel_event = threading.Event()
    llm = _ScriptedLLM(_tool_call_response())
    registry = _Registry()

    _run(tmp_path, llm, registry, cancel_event)

    assert llm.should_cancel_seen, "stream_chat was never called"
    predicate = llm.should_cancel_seen[0]
    assert predicate == cancel_event.is_set, (
        "the worker must hand cancel_event.is_set to stream_chat as should_cancel, "
        "the same cooperative predicate AgentLoop uses"
    )
    assert predicate() is False
    cancel_event.set()
    assert predicate() is True


def test_no_cancel_event_leaves_stream_chat_signature_untouched(tmp_path):
    """Callers that never pass cancel_event (older call sites, tests with stubs
    whose stream_chat has no should_cancel parameter) must see no new kwarg."""
    llm = _ScriptedLLM(_tool_call_response())
    registry = _Registry()

    _run(tmp_path, llm, registry, cancel_event=None)

    assert llm.should_cancel_seen and all(p is None for p in llm.should_cancel_seen)
