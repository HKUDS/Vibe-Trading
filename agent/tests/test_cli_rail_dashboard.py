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

    def test_missing_call_does_not_complete_another_active_call(self, dashboard):
        dashboard.handle_event('item.started', {"kind": 'tool.started', 'item': {'type': 'tool_result', 'name': 'backtest', 'tool_call_id': 'active'}, 'live_id': "tool:" + str('active')})
        dashboard.handle_event('item.completed', {"kind": 'tool.failed', 'item': {'type': 'tool_result', 'name': 'backtest', 'tool_call_id': 'evicted', 'status': 'error'}, 'live_id': "tool:" + str('evicted')})
        assert next(step for step in dashboard.steps if step.call_id == "active").status == "active"
        assert next(step for step in dashboard.steps if step.call_id == "evicted").status == "error"

    def test_results_pair_with_their_own_call_via_call_id(self, dashboard: RailRunDashboard) -> None:
        dashboard.handle_event(
            'item.started', {"kind": 'tool.started', 'item': {'type': 'tool_result', 'name': 'get_market_data', 'tool_call_id': 'call-1', 'arguments': {'symbol': 'AAPL'}}, 'live_id': "tool:" + str('call-1')}
        )
        dashboard.handle_event(
            'item.started', {"kind": 'tool.started', 'item': {'type': 'tool_result', 'name': 'get_market_data', 'tool_call_id': 'call-2', 'arguments': {'symbol': 'MSFT'}}, 'live_id': "tool:" + str('call-2')}
        )

        dashboard.handle_event(
            'item.completed', {"kind": 'tool.completed', 'item': {'type': 'tool_result', 'name': 'get_market_data', 'tool_call_id': 'call-1', 'content': '{"summary": "AAPL result"}', 'status': 'ok'}, 'live_id': "tool:" + str('call-1')},
        )
        dashboard.handle_event(
            'item.completed', {"kind": 'tool.completed', 'item': {'type': 'tool_result', 'name': 'get_market_data', 'tool_call_id': 'call-2', 'content': '{"summary": "MSFT result"}', 'status': 'ok'}, 'live_id': "tool:" + str('call-2')},
        )

        aapl_step = next(s for s in dashboard.steps if s.args == {"symbol": "AAPL"})
        msft_step = next(s for s in dashboard.steps if s.args == {"symbol": "MSFT"})
        assert any("AAPL result" in line for line in aapl_step.lines)
        assert not any("MSFT result" in line for line in aapl_step.lines)
        assert any("MSFT result" in line for line in msft_step.lines)
        assert not any("AAPL result" in line for line in msft_step.lines)

    def test_progress_event_updates_its_own_call_via_call_id(self, dashboard: RailRunDashboard) -> None:
        dashboard.handle_event(
            'item.started', {"kind": 'tool.started', 'item': {'type': 'tool_result', 'name': 'backtest', 'tool_call_id': 'call-1', 'arguments': {'symbol': 'AAPL'}}, 'live_id': "tool:" + str('call-1')}
        )
        dashboard.handle_event(
            'item.started', {"kind": 'tool.started', 'item': {'type': 'tool_result', 'name': 'backtest', 'tool_call_id': 'call-2', 'arguments': {'symbol': 'MSFT'}}, 'live_id': "tool:" + str('call-2')}
        )

        dashboard.handle_event(
            'item.delta', {"kind": 'tool.progress', 'progress': {'tool': 'backtest', 'message': 'halfway for MSFT', 'call_id': 'call-2'}, 'heartbeat': False, 'live_id': "tool:" + str('call-2')}
        )

        aapl_step = next(s for s in dashboard.steps if s.args == {"symbol": "AAPL"})
        msft_step = next(s for s in dashboard.steps if s.args == {"symbol": "MSFT"})
        assert not any("halfway for MSFT" in line for line in aapl_step.lines)
        assert any("halfway for MSFT" in line for line in msft_step.lines)
