"""The duplicate-call gate must compare arguments, not just the tool name.

`self._called_ok` stored `tc.name`, so the second call to any parameterised or
paginated tool was answered with a synthetic ``{"skipped": true}`` result and
never executed:

    get_financial_statements(statement="income")   -> ok
    get_financial_statements(statement="balance")  -> BLOCKED
    get_financial_statements(offset=13)            -> BLOCKED

`_result_paging` advertises `next_offset` and `complete: false`, so paging is
the documented way to retrieve the rest -- and the gate made it impossible. The
model then reported that the balance sheet "returned no readable content",
which was a true statement about a fabricated tool result.

The gate now keys on `_identical_call_key`, the same canonicaliser the
deterministic cache uses, so the two paths cannot disagree about what "the same
call" means.

Harness mirrors test_agent_loop_deterministic_cache._drive.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.context import ContextBuilder
from src.agent.loop import AgentLoop
from src.agent.tools import BaseTool, ToolRegistry
from tests.recording_helpers import recorder_at, records_at, run_recorded_tools


class _PagedTool(BaseTool):
    """A NON-repeatable tool, so the duplicate gate applies to it."""

    name = "get_financial_statements"
    description = "test double for a paginated, parameterised fetch"
    parameters: dict = {"type": "object", "properties": {}}
    repeatable = False
    is_readonly = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def execute(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return json.dumps({"status": "ok", "call": len(self.calls), "args": kwargs})


def _drive(
    agent: AgentLoop,
    tool_name: str,
    run_dir: Path,
    arg_sets: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Run a sequence of tool calls through the loop's tool-call path."""
    trace = recorder_at(run_dir)
    messages: list[dict] = []
    for index, arguments in enumerate(arg_sets, start=1):
        run_recorded_tools(agent, [SimpleNamespace(id=f"call_{index}", name=tool_name, arguments=arguments)], ContextBuilder, messages, trace, index)
    trace.close()
    return messages, list(records_at(run_dir))


@pytest.fixture()
def agent_factory(tmp_path: Path):
    """Return a builder for an AgentLoop wired to a run dir and one tool."""

    def _build(tool: BaseTool) -> tuple[AgentLoop, Path]:
        registry = ToolRegistry()
        registry.register(tool)
        agent = AgentLoop(
            registry=registry,
            llm=SimpleNamespace(),
            max_iterations=4,
            event_callback=lambda name, data: None,
        )
        run_dir = tmp_path / tool.name
        run_dir.mkdir()
        agent.memory.run_dir = str(run_dir)
        return agent, run_dir

    return _build


def _skipped(message: dict) -> bool:
    """True when a message is the synthetic duplicate-skip result."""
    try:
        return json.loads(message["content"]).get("skipped") is True
    except (ValueError, TypeError, KeyError):
        return False


def test_different_arguments_are_not_duplicates(agent_factory) -> None:
    """The red test for the bug: two statements, two executions.

    On the unfixed loop the second call is answered with a synthetic skip and
    the tool never runs.
    """
    tool = _PagedTool()
    agent, run_dir = agent_factory(tool)

    messages, _ = _drive(
        agent,
        tool.name,
        run_dir,
        [{"statement": "income"}, {"statement": "balance"}],
    )

    assert len(tool.calls) == 2, "second distinct call was blocked, not executed"
    assert tool.calls[0]["statement"] == "income"
    assert tool.calls[1]["statement"] == "balance"
    assert not any(_skipped(m) for m in messages), "a distinct call was skipped"


def test_paging_offsets_are_not_duplicates(agent_factory) -> None:
    """Paging is the documented way to finish a fetch; it must not self-block."""
    tool = _PagedTool()
    agent, run_dir = agent_factory(tool)

    messages, _ = _drive(
        agent,
        tool.name,
        run_dir,
        [{"statement": "income"}, {"statement": "income", "offset": 13}],
    )

    assert len(tool.calls) == 2, "paged continuation was blocked"
    assert tool.calls[1]["offset"] == 13
    assert not any(_skipped(m) for m in messages)


def test_identical_arguments_are_still_blocked(agent_factory) -> None:
    """The negative control: the gate must keep doing its job.

    Relaxing the key must not turn into 'never dedup'.
    """
    tool = _PagedTool()
    agent, run_dir = agent_factory(tool)

    args = {"statement": "income"}
    messages, _ = _drive(agent, tool.name, run_dir, [dict(args), dict(args)])

    assert len(tool.calls) == 1, "identical repeat executed twice"
    assert _skipped(messages[1]), "identical repeat was not skipped"


def test_argument_order_does_not_defeat_the_gate(agent_factory) -> None:
    """Canonicalisation sorts keys, so dict ordering is not a new identity."""
    tool = _PagedTool()
    agent, run_dir = agent_factory(tool)

    messages, _ = _drive(
        agent,
        tool.name,
        run_dir,
        [
            {"statement": "income", "period": "annual"},
            {"period": "annual", "statement": "income"},
        ],
    )

    assert len(tool.calls) == 1, "key order was treated as a different call"
    assert _skipped(messages[1])
