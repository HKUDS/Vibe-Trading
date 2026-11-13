"""Behaviour tests for the deterministic-tool result cache.

After an auto-compact cleared earlier tool outputs, the model re-ran the same
``financial_rigor`` expressions five to nine times each to re-verify numbers it
could no longer see. The loop now serves an identical later call from cache --
but only for tools that declare themselves pure, and only for results that
succeeded.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.context import ContextBuilder
from src.agent.loop import AgentLoop
from src.agent.tools import BaseTool, ToolRegistry
from src.agent.trace import TraceWriter
from src.tools.financial_rigor_tool import FinancialRigorTool


class _CountingTool(BaseTool):
    """A repeatable tool that counts executions, purity configurable."""

    name = "counting_tool"
    description = "test tool"
    parameters: dict = {"type": "object", "properties": {}}
    repeatable = True
    is_readonly = True

    def __init__(self, *, deterministic: bool, status: str = "ok") -> None:
        self.deterministic = deterministic
        self._status = status
        self.calls: list[dict] = []

    def execute(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return json.dumps({"status": self._status, "n": len(self.calls)})


def _drive(
    agent: AgentLoop,
    tool_name: str,
    run_dir: Path,
    arg_sets: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Run a sequence of tool calls through the loop's tool-call path.

    Args:
        agent: The loop under test.
        tool_name: Tool to invoke.
        run_dir: Run directory backing the trace.
        arg_sets: One argument dict per successive call.

    Returns:
        Tuple of (messages appended, trace records written).
    """
    trace = TraceWriter(run_dir)
    messages: list[dict] = []
    react_trace: list[dict] = []
    for index, arguments in enumerate(arg_sets, start=1):
        agent._process_tool_calls(
            [SimpleNamespace(id=f"call_{index}", name=tool_name, arguments=arguments)],
            ContextBuilder,
            messages,
            trace,
            react_trace,
            index,
        )
    trace.close()
    return messages, list(TraceWriter.read(run_dir))


@pytest.fixture()
def agent_factory(tmp_path: Path):
    """Return a builder for an AgentLoop wired to a run dir and one tool."""

    def _build(tool: BaseTool) -> tuple[AgentLoop, Path, list[tuple[str, dict]]]:
        registry = ToolRegistry()
        registry.register(tool)
        captured: list[tuple[str, dict]] = []
        agent = AgentLoop(
            registry=registry,
            llm=SimpleNamespace(),
            max_iterations=4,
            event_callback=lambda name, data: captured.append((name, data)),
        )
        run_dir = tmp_path / tool.name
        run_dir.mkdir()
        agent.memory.run_dir = str(run_dir)
        return agent, run_dir, captured

    return _build


def test_identical_deterministic_call_is_served_from_cache(agent_factory) -> None:
    """The same expression twice must execute once and answer twice."""
    tool = FinancialRigorTool()
    executions: list[dict] = []
    original = tool.execute

    def _execute(**kwargs: object) -> str:
        executions.append(kwargs)
        return original(**kwargs)

    tool.execute = _execute  # type: ignore[method-assign]
    agent, run_dir, captured = agent_factory(tool)

    args = {"command": "calc", "expr": "92.13/101.65-1"}
    messages, records = _drive(agent, tool.name, run_dir, [dict(args), dict(args)])

    assert len(executions) == 1
    # The model still gets an answer for its second call.
    assert len(messages) == 2
    assert json.loads(messages[0]["content"])["result_exact"] == (
        json.loads(messages[1]["content"])["result_exact"]
    )
    assert [r["type"] for r in records].count("tool_result_cached") == 1
    cached_events = [d for name, d in captured if d.get("cached")]
    assert len(cached_events) == 1
    assert cached_events[0]["tool"] == tool.name


def test_different_arguments_re_execute(agent_factory) -> None:
    """A different expression is a different question, not a cache hit."""
    tool = FinancialRigorTool()
    executions: list[dict] = []
    original = tool.execute

    def _execute(**kwargs: object) -> str:
        executions.append(kwargs)
        return original(**kwargs)

    tool.execute = _execute  # type: ignore[method-assign]
    agent, run_dir, _ = agent_factory(tool)

    messages, records = _drive(
        agent,
        tool.name,
        run_dir,
        [
            {"command": "calc", "expr": "92.13/101.65-1"},
            {"command": "calc", "expr": "85.4/108.8-1"},
        ],
    )

    assert len(executions) == 2
    assert len(messages) == 2
    assert not any(r["type"] == "tool_result_cached" for r in records)


def test_non_deterministic_tool_is_never_cached(agent_factory) -> None:
    """Only a tool that declares purity may skip re-execution."""
    tool = _CountingTool(deterministic=False)
    agent, run_dir, _ = agent_factory(tool)

    messages, records = _drive(
        agent, tool.name, run_dir, [{"a": 1}, {"a": 1}],
    )

    assert len(tool.calls) == 2
    assert len(messages) == 2
    assert not any(r["type"] == "tool_result_cached" for r in records)


def test_failed_deterministic_call_is_not_cached(agent_factory) -> None:
    """Failures are skipped by the retry guard, never served as cached success."""
    tool = _CountingTool(deterministic=True, status="error")
    agent, run_dir, _ = agent_factory(tool)

    messages, records = _drive(
        agent,
        tool.name,
        run_dir,
        [{"a": 1}, {"a": 1}, {"a": 1}, {"a": 2}],
    )

    # One honest retry runs (a transient failure says nothing about the
    # arguments); the THIRD identical attempt is refused, and changed
    # arguments still execute.
    assert len(tool.calls) == 3
    assert len(messages) == 4
    assert json.loads(messages[2]["content"])["skipped"] is True
    assert not any(r["type"] == "tool_result_cached" for r in records)


def test_cache_hit_still_passes_the_identity_gate(agent_factory) -> None:
    """A cached repeat must not be a way around grounding authorization.

    ``financial_rigor`` carries no symbol arguments, so the gate allows it
    today either way. Any later tool marked deterministic that does carry
    one would otherwise skip identity checks from its second call onward.
    """
    from evals.grounding import ToolAuthorization

    tool = _CountingTool(deterministic=True)
    agent, run_dir, _ = agent_factory(tool)

    seen: list[str] = []
    ingested: list[str] = []

    class _Grounding:
        authorized_symbols: set[str] = set()
        identity_status = "locked"

        def authorize_tool_call(self, tool_name, arguments, **kwargs):
            seen.append(kwargs["call_id"])
            if len(seen) == 1:
                return ToolAuthorization(allowed=True)
            return ToolAuthorization(
                allowed=False,
                error_code="identity_required",
                message="blocked",
            )

        def identity_summary(self):
            return {}

        def ingest_tool_result(self, **kwargs):
            ingested.append(kwargs["call_id"])

    agent._identity = _Grounding()
    messages, records = _drive(agent, tool.name, run_dir, [{"a": 1}, {"a": 1}])

    # Both calls reached the gate; the blocked repeat was not served cached.
    assert seen == ["call_1", "call_2"]
    assert not any(r["type"] == "tool_result_cached" for r in records)
    assert json.loads(messages[1]["content"])["error_code"] == "identity_required"
    # The blocked result is ingested too, so the ledger keeps the refusal.
    assert ingested == ["call_1", "call_2"]
