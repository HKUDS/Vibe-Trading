"""Regression tests for parameter-dependent query tools in the agent loop."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.context import ContextBuilder
from src.agent.loop import AgentLoop
from src.agent.tools import ToolRegistry
from src.agent.trace import TraceWriter
from src.tools.get_fundamentals_tool import GetFundamentalsTool
from src.tools.market_data_tool import MarketDataTool
from src.tools.market_screener_tool import MarketScreenerTool
from src.tools.symbol_search_tool import SymbolSearchTool


@pytest.mark.parametrize(
    ("tool_cls", "first_args", "second_args"),
    [
        (
            MarketDataTool,
            {
                "codes": ["AAPL.US"],
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
            },
            {
                "codes": ["MSFT.US"],
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
            },
        ),
        (
            GetFundamentalsTool,
            {
                "symbols": ["AAPL.US"],
                "fields": ["roe"],
                "start": "2025-01-01",
                "end": "2025-01-31",
            },
            {
                "symbols": ["MSFT.US"],
                "fields": ["roe"],
                "start": "2025-01-01",
                "end": "2025-01-31",
            },
        ),
        (
            MarketScreenerTool,
            {"market": "us", "sort_by": "volume", "top_n": 5},
            {"market": "hk", "sort_by": "amount", "top_n": 10},
        ),
        (
            SymbolSearchTool,
            {"query": "Apple", "limit": 5},
            {"query": "Microsoft", "limit": 5},
        ),
    ],
)
def test_repeatable_query_executes_again_with_different_arguments(
    monkeypatch,
    tmp_path: Path,
    tool_cls: type,
    first_args: dict[str, object],
    second_args: dict[str, object],
) -> None:
    """A successful query must not suppress the next iteration's symbol."""
    calls: list[dict[str, object]] = []
    tool = tool_cls()

    def _execute(**kwargs: object) -> str:
        calls.append(kwargs)
        return json.dumps({"status": "ok"})

    monkeypatch.setattr(tool, "execute", _execute)
    registry = ToolRegistry()
    registry.register(tool)
    agent = AgentLoop(registry=registry, llm=SimpleNamespace(), max_iterations=2)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)
    trace = TraceWriter(run_dir)
    messages: list[dict[str, object]] = []
    react_trace: list[dict[str, object]] = []

    for iteration, (call_id, arguments) in enumerate(
        (("call_first", first_args), ("call_second", second_args)), start=1
    ):
        agent._process_tool_calls(
            [
                SimpleNamespace(
                    id=call_id,
                    name=tool.name,
                    arguments=arguments,
                )
            ],
            ContextBuilder,
            messages,
            trace,
            react_trace,
            iteration,
        )
    trace.close()

    assert [
        {key: value for key, value in call.items() if key != "run_dir"}
        for call in calls
    ] == [first_args, second_args]
    assert len(messages) == 2
    assert not any(
        event["type"] == "tool_skipped" for event in TraceWriter.read(run_dir)
    )
