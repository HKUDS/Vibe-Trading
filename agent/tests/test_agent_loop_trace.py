"""AgentLoop trace integration tests for PR #206 rebase."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

import src.agent.loop as loop_mod
from src.agent.context import ContextBuilder
from src.agent.loop import AgentLoop
from tests.recording_helpers import recorder_at, records_at, run_recorded_tool


class _Tool:
    is_readonly = False
    repeatable = True


class _SecretRegistry:
    """Minimal registry returning a JSON result with sensitive fields."""

    _tools: dict[str, Any] = {}

    def get(self, tool_name: str) -> _Tool:
        return _Tool()

    def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        del tool_name, args
        return json.dumps(
            {
                "status": "ok",
                "symbol": "AAPL",
                "authorization": "Bearer secret-token",
                "nested": {"api_key": "secret-key"},
            }
        )


def test_tool_call_trace_redacts_args_and_structured_results(tmp_path: Path) -> None:
    """Persistent trace entries should not store raw credentials/account fields."""
    agent = AgentLoop(
        registry=_SecretRegistry(),  # type: ignore[arg-type]
        llm=SimpleNamespace(),
        max_iterations=1,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)
    trace = recorder_at(run_dir)
    messages: list[dict[str, Any]] = []
    tc = SimpleNamespace(
        id="tc_secret",
        name="secret_tool",
        arguments={
            "symbol": "AAPL",
            "api_key": "raw-secret",
            "nested": {"authorization": "Bearer raw-secret"},
        },
    )

    run_recorded_tool(agent, tc, ContextBuilder, messages, trace, 1)
    trace.close()

    entries = records_at(run_dir)
    tool_call = next(entry for entry in entries if entry["type"] == "tool_call")
    assert tool_call["args"]["symbol"] == "AAPL"
    assert tool_call["args"]["api_key"] == "[redacted]"
    assert tool_call["args"]["nested"]["authorization"] == "[redacted]"

    tool_result = next(entry for entry in entries if entry["type"] == "tool_result")
    assert "secret-token" not in json.dumps(tool_result)
    assert "secret-key" not in json.dumps(tool_result)
    result_payload = json.loads(tool_result["result"])
    assert result_payload["authorization"] == "[redacted]"
    assert result_payload["nested"]["api_key"] == "[redacted]"
    assert "secret-token" not in messages[0]["content"]
    assert json.loads(messages[0]["content"])["symbol"] == "AAPL"


class _LongAnswerResponse:
    content = "final answer " * 10
    tool_calls: list[Any] = []
    reasoning_content: str | None = None
    has_tool_calls = False
    usage_metadata: dict[str, int] | None = None


class _LongAnswerLLM:
    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
        on_reasoning_chunk: Callable[[str], None] | None = None,
        timeout: int | None = None,
        idle_timeout_s: float | None = None,
        should_cancel: Callable[[], bool] | None = None,
        on_waiting_chunk=None,
    ) -> _LongAnswerResponse:
        del messages, tools, on_reasoning_chunk
        if on_text_chunk:
            on_text_chunk("final answer ")
        return _LongAnswerResponse()

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> _LongAnswerResponse:
        del messages
        return _LongAnswerResponse()


def test_session_trace_uses_session_dir_and_round_trips_long_answer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Session runs aggregate trace.jsonl under sessions/<id> without truncation."""
    monkeypatch.setattr(loop_mod, "SESSIONS_DIR", tmp_path / "sessions")
    agent = AgentLoop(
        registry=_SecretRegistry(),  # type: ignore[arg-type]
        llm=_LongAnswerLLM(),
        max_iterations=1,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)

    result = agent.run(user_message="hello from session", session_id="sid123")

    assert result["status"] == "success"
    trace_dir = tmp_path / "sessions" / "sid123"
    assert (trace_dir / "thread.jsonl").exists()
    assert not list(tmp_path.rglob("trace.jsonl"))
    assert not list(tmp_path.rglob("trace-blobs"))
    records = records_at(trace_dir)
    answer = next(entry for entry in records if entry["type"] == "answer")
    start = next(entry for entry in records if entry["type"] == "start")
    assert answer["content"] == result["content"]
    assert start["prompt"] == "hello from session"
