"""Tests for the CLI rail dashboard's tool_call/tool_result pairing."""

from __future__ import annotations

from typing import Iterator

import pytest

from cli.ui.rail import RailRunDashboard


@pytest.fixture()
def dashboard() -> Iterator[RailRunDashboard]:
    dash = RailRunDashboard("test prompt", max_iter=10)
    try:
        yield dash
    finally:
        dash.close()


class TestConcurrentToolCallPairing:
    """Two concurrent calls to the same tool must not have their results swapped.

    The agent loop runs consecutive readonly tool calls in parallel, so more
    than one step for the same tool name can be "active" at once. Matching a
    tool_result to a step by tool name and recency alone pairs the first
    arriving result with the most recently started step instead of the one
    it actually belongs to.
    """

    def test_results_pair_with_their_own_call_via_call_id(self, dashboard: RailRunDashboard) -> None:
        dashboard.handle_event(
            "tool_call", {"tool": "get_market_data", "arguments": {"symbol": "AAPL"}, "call_id": "call-1"}
        )
        dashboard.handle_event(
            "tool_call", {"tool": "get_market_data", "arguments": {"symbol": "MSFT"}, "call_id": "call-2"}
        )

        dashboard.handle_event(
            "tool_result",
            {"tool": "get_market_data", "status": "ok", "preview": '{"summary": "AAPL result"}', "call_id": "call-1"},
        )
        dashboard.handle_event(
            "tool_result",
            {"tool": "get_market_data", "status": "ok", "preview": '{"summary": "MSFT result"}', "call_id": "call-2"},
        )

        aapl_step = next(s for s in dashboard.steps if s.args == {"symbol": "AAPL"})
        msft_step = next(s for s in dashboard.steps if s.args == {"symbol": "MSFT"})
        assert any("AAPL result" in line for line in aapl_step.lines)
        assert not any("MSFT result" in line for line in aapl_step.lines)
        assert any("MSFT result" in line for line in msft_step.lines)
        assert not any("AAPL result" in line for line in msft_step.lines)

    def test_progress_event_updates_its_own_call_via_call_id(self, dashboard: RailRunDashboard) -> None:
        dashboard.handle_event(
            "tool_call", {"tool": "backtest", "arguments": {"symbol": "AAPL"}, "call_id": "call-1"}
        )
        dashboard.handle_event(
            "tool_call", {"tool": "backtest", "arguments": {"symbol": "MSFT"}, "call_id": "call-2"}
        )

        dashboard.handle_event(
            "tool_progress", {"tool": "backtest", "message": "halfway for MSFT", "call_id": "call-2"}
        )

        aapl_step = next(s for s in dashboard.steps if s.args == {"symbol": "AAPL"})
        msft_step = next(s for s in dashboard.steps if s.args == {"symbol": "MSFT"})
        assert not any("halfway for MSFT" in line for line in aapl_step.lines)
        assert any("halfway for MSFT" in line for line in msft_step.lines)
