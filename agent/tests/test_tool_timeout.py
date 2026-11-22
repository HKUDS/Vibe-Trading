"""Tool timeout/liveness regression tests."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.agent import tuning as tuning_mod
from src.agent.context import ContextBuilder
from src.agent.loop import AgentLoop
from tests.recording_helpers import recorder_at, run_recorded_tools


class _SlowRegistry:
    class _Tool:
        is_readonly = True

    def get(self, tool_name: str) -> object:
        return self._Tool()

    def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        time.sleep(1.0)
        return '{"status":"ok"}'


class _SlowWriteRegistry:
    class _Tool:
        is_readonly = False

    def __init__(self) -> None:
        self.completed = False

    def get(self, tool_name: str) -> object:
        return self._Tool()

    def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        time.sleep(0.08)
        self.completed = True
        return '{"status":"ok"}'


class _SlowOrderRegistry(_SlowWriteRegistry):
    def get(self, tool_name: str) -> object:
        return SimpleNamespace(is_readonly=False, repeatable=False)


def test_tool_timeout_returns_error_and_stops_heartbeats(monkeypatch) -> None:
    """A hung tool should become a bounded diagnostic instead of heartbeating forever."""
    monkeypatch.setattr(tuning_mod, "TOOL_TIMEOUT_SECONDS", 0.05, raising=False)
    monkeypatch.setattr(tuning_mod, "HEARTBEAT_INTERVAL_S", 0.01, raising=False)
    events: list[tuple[str, dict[str, Any]]] = []
    agent = AgentLoop(
        registry=_SlowRegistry(),  # type: ignore[arg-type]
        llm=SimpleNamespace(),
        event_callback=lambda event_type, data: events.append((event_type, data)),
        max_iterations=1,
    )

    result, elapsed_ms = agent._invoke_tool(
        "slow_tool", {}, call_id="slow-call"
    )
    event_count_at_return = len(events)
    time.sleep(0.08)

    payload = json.loads(result)
    assert payload["status"] == "error"
    assert payload["error_code"] == "tool_timeout"
    assert payload["tool"] == "slow_tool"
    assert elapsed_ms >= 40
    assert len(events) == event_count_at_return
    timeout_event = next(
        data
        for event_type, data in events
        if event_type == "tool_progress" and data.get("stage") == "timeout"
    )
    assert timeout_event["call_id"] == "slow-call"


def test_write_tool_timeout_reports_unknown_outcome(monkeypatch) -> None:
    """A detached side-effecting worker must never look like a safe retry."""
    monkeypatch.setattr(tuning_mod, "TOOL_TIMEOUT_SECONDS", 0.02, raising=False)
    monkeypatch.setattr(tuning_mod, "HEARTBEAT_INTERVAL_S", 0.01, raising=False)
    events: list[tuple[str, dict[str, Any]]] = []
    registry = _SlowWriteRegistry()
    agent = AgentLoop(
        registry=registry,  # type: ignore[arg-type]
        llm=SimpleNamespace(),
        event_callback=lambda event_type, data: events.append((event_type, data)),
        max_iterations=1,
    )

    result, elapsed_ms = agent._invoke_tool(
        "write_tool", {}, call_id="write-call"
    )

    payload = json.loads(result)
    assert payload["status"] == "error"
    assert payload["error_code"] == "tool_outcome_unknown"
    assert payload["outcome"] == "unknown"
    assert payload["retryable"] is False
    assert "check the external state" in payload["message"].lower()
    assert payload["orphaned_worker"] is True
    assert registry.completed is False
    assert elapsed_ms < 70
    assert any(
        event_type == "tool_progress"
        and data.get("stage") == "timeout_warning"
        and data.get("call_id") == "write-call"
        for event_type, data in events
    ) is False

    # The worker cannot be killed safely from Python. It finishes its side
    # effect in the background, while the loop has already recorded unknown.
    time.sleep(0.1)
    assert registry.completed is True


def test_order_tool_waits_for_completion_instead_of_detaching(monkeypatch) -> None:
    """Order tools keep their broker-side timeout and cannot orphan a write."""
    monkeypatch.setattr(tuning_mod, "TOOL_TIMEOUT_SECONDS", 0.02, raising=False)
    registry = _SlowOrderRegistry()
    agent = AgentLoop(
        registry=registry,  # type: ignore[arg-type]
        llm=SimpleNamespace(),
        max_iterations=1,
    )

    result, elapsed_ms = agent._invoke_tool(
        "trading_place_order", {}, call_id="order-call"
    )

    payload = json.loads(result)
    assert payload["status"] == "ok"
    assert registry.completed is True
    assert elapsed_ms >= 70


def test_cancel_returns_explicit_result_for_running_write(monkeypatch) -> None:
    """Parent cancellation ends the wait before a tool that ignores it."""
    monkeypatch.setattr(tuning_mod, "TOOL_TIMEOUT_SECONDS", 5.0, raising=False)
    registry = _SlowWriteRegistry()
    agent = AgentLoop(
        registry=registry,  # type: ignore[arg-type]
        llm=SimpleNamespace(),
        max_iterations=1,
    )

    def cancel() -> None:
        time.sleep(0.02)
        agent.cancel()

    import threading

    threading.Thread(target=cancel, daemon=True).start()
    result, elapsed_ms = agent._invoke_tool("write_tool", {}, call_id="cancel-call")

    payload = json.loads(result)
    assert payload["status"] == "error"
    assert payload["error_code"] == "tool_outcome_unknown"
    assert payload["outcome"] == "unknown"
    assert payload["retryable"] is False
    assert elapsed_ms < 70


def test_cancelled_queued_tool_is_recorded_as_a_result(tmp_path: Path) -> None:
    """A call skipped before launch still closes its provider tool block."""
    registry = _SlowWriteRegistry()
    agent = AgentLoop(registry=registry, llm=SimpleNamespace(), max_iterations=1)
    agent.memory.run_dir = str(tmp_path)
    agent.cancel()
    messages: list[dict[str, Any]] = []
    trace = recorder_at(tmp_path)

    run_recorded_tools(agent, [SimpleNamespace(id="queued-call", name="place_order", arguments={})], ContextBuilder, messages, trace, 1)
    trace.close()

    payload = json.loads(messages[-1]["content"])
    assert payload["error_code"] == "tool_cancelled"
    assert registry.completed is False
