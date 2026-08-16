"""Tests that run_worker() truncates oversized tool results the same way
agent/src/agent/loop.py does.

Regression: run_worker() truncated an oversized tool result with a raw
result[:TOOL_RESULT_LIMIT] slice, no notice, frequently invalid JSON, and no
correction of any envelope field the cut falsifies. The main agent loop, given
the identical tool output and the identical limit, uses the shared
truncate_tool_result() helper, which appends an explicit [TRUNCATED: ...]
notice. The two call paths must behave identically for the same input.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.config.limits import TOOL_RESULT_LIMIT, truncate_tool_result
from src.providers.chat import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmTask
import src.swarm.worker as worker_mod
from src.swarm.worker import run_worker

FINAL_TEXT = (
    "# BTC-USDT — Short-Term View\n\n"
    "Spot 81,704.6 (2026-05-05). 7d range 77,750-82,842.\n\n"
    "**Recommendation: accumulate on dips to 79k; invalidation below 77.5k.**\n"
    "Position 3% NAV, stop 76,900, target 86,000. Funding 0.035%/8h elevated\n"
    "but not extreme; exchange reserves declining (bullish)."
)


class _OneToolRegistry:
    """Minimal ToolRegistry stand-in exposing a single tool whose result the
    test controls (the existing worker-test stubs hardcode "ok", so they
    can't exercise the truncation contract this file tests)."""

    def __init__(self, result: str) -> None:
        self._result = result

    def get_definitions(self) -> list[dict]:
        return [
            {"type": "function", "function": {"name": "big_tool", "parameters": {}}}
        ]

    def get(self, name: str):
        return None

    def execute(self, name: str, args: dict) -> str:
        return self._result


class _ScriptedChatLLM:
    """Scripted ChatLLM that returns queued responses in order, capturing
    every call's messages (same shape as test_swarm_worker_content_filter.py)."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.received_messages: list[list[dict]] = []

    def __call__(self, *args, **kwargs) -> "_ScriptedChatLLM":
        return self

    def stream_chat(
        self, messages, tools=None, on_text_chunk=None, timeout=None
    ) -> LLMResponse:
        self.received_messages.append(list(messages))
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content=FINAL_TEXT)


def _run(monkeypatch, tmp_path: Path, llm: _ScriptedChatLLM, tool_result: str) -> str:
    """Run a worker that calls one tool returning ``tool_result`` and return
    the tool-role message content the LLM was sent on its next turn."""
    agent = SwarmAgentSpec(
        id="analyst",
        role="Synthesis analyst",
        system_prompt="You synthesize upstream findings.",
        tools=["big_tool"],
        skills=[],
        max_iterations=3,
        timeout_seconds=60,
    )
    task = SwarmTask(id="t1", agent_id="analyst", prompt_template="Read the document.")
    with (
        patch.object(
            worker_mod,
            "build_swarm_registry",
            lambda *a, **k: _OneToolRegistry(tool_result),
        ),
        patch.object(worker_mod, "ChatLLM", llm),
    ):
        run_worker(
            agent_spec=agent,
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=tmp_path,
        )
    tool_messages = [m for m in llm.received_messages[-1] if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    return tool_messages[0]["content"]


def _tool_call_then_final() -> _ScriptedChatLLM:
    return _ScriptedChatLLM(
        [
            LLMResponse(
                tool_calls=[ToolCallRequest(id="call_1", name="big_tool", arguments={})]
            ),
            LLMResponse(content=FINAL_TEXT),
        ]
    )


def test_oversized_tool_result_gets_truncation_notice(monkeypatch, tmp_path):
    """An oversized result must carry the same [TRUNCATED: ...] notice the
    main agent loop produces, not a silent raw slice."""
    big_result = "x" * (TOOL_RESULT_LIMIT + 5000)

    content = _run(monkeypatch, tmp_path, _tool_call_then_final(), big_result)

    assert "[TRUNCATED:" in content
    assert content == truncate_tool_result(big_result)
    assert content != big_result[:TOOL_RESULT_LIMIT]


def test_oversized_result_stale_envelope_field_not_left_uncorrected(
    monkeypatch, tmp_path
):
    """A tool's own 'truncated: false' claim must not survive the cut still
    asserting completeness once the result is actually truncated."""
    big_result = (
        '{"status": "ok", "truncated": false, "body": "'
        + ("y" * TOOL_RESULT_LIMIT)
        + '"}'
    )

    content = _run(monkeypatch, tmp_path, _tool_call_then_final(), big_result)

    assert content == truncate_tool_result(big_result)
    assert "[TRUNCATED:" in content


def test_result_under_limit_passes_through_unchanged(monkeypatch, tmp_path):
    """A result at or under the limit must reach the LLM byte-for-byte
    unchanged — the fix must not alter ordinary, non-oversized results."""
    small_result = '{"status": "ok", "body": "normal sized tool output"}'

    content = _run(monkeypatch, tmp_path, _tool_call_then_final(), small_result)

    assert content == small_result
