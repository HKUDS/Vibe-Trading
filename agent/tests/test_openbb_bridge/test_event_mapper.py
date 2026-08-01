"""Unit tests for :class:`SSEEventMapper`."""

from __future__ import annotations

import pytest

pytest.importorskip("openbb_ai")

from src.openbb_bridge.event_mapper import SSEEventMapper


def test_text_delta_maps_to_single_message_chunk():
    mapper = SSEEventMapper()
    out = mapper.map("text_delta", {"delta": "Hello", "attempt_id": "a1"})
    assert len(out) == 1
    dumped = out[0].model_dump()
    assert "event" in dumped and "data" in dumped


def test_empty_text_delta_is_swallowed():
    mapper = SSEEventMapper()
    assert mapper.map("text_delta", {"delta": ""}) == []


def test_silent_events_produce_nothing():
    mapper = SSEEventMapper()
    for event_type in ("reasoning_delta", "thinking_done", "tool_progress",
                       "tool_heartbeat", "llm_usage"):
        assert mapper.map(event_type, {"attempt_id": "a1"}) == []


def test_tool_call_maps_to_reasoning_step():
    mapper = SSEEventMapper()
    out = mapper.map("tool_call", {"tool": "get_market_data", "arguments": {"symbol": "AAPL"}})
    assert len(out) == 1
    assert out[0].model_dump()["event"]  # non-empty event name


def test_tool_result_error_status_still_maps():
    mapper = SSEEventMapper()
    out = mapper.map(
        "tool_result",
        {"tool": "x", "status": "error", "elapsed_ms": 12, "preview": "boom"},
    )
    assert len(out) == 1


def test_unknown_event_is_swallowed():
    mapper = SSEEventMapper()
    assert mapper.map("totally_unknown", {"foo": "bar"}) == []


def test_mapping_never_raises_on_bad_data():
    mapper = SSEEventMapper()
    # Missing keys / None data must not raise.
    assert mapper.map("tool_call", {}) is not None
    assert mapper.map("text_delta", None) == []
