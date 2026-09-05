"""Regression coverage for host-side tool invocation policies."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.agent.context import ContextBuilder
from src.agent.loop import AgentLoop
from src.agent.tools import BaseTool, InvocationPolicy, ToolRegistry
from src.agent.trace import TraceWriter


class _RecordingTool(BaseTool):
    """Configurable tool that records every implementation invocation."""

    name = "recording_tool"
    description = "test invocation policy"
    parameters: dict = {"type": "object", "properties": {}}

    def __init__(
        self,
        *,
        is_readonly: bool,
        statuses: list[str] | None = None,
    ) -> None:
        self.is_readonly = is_readonly
        self.statuses = list(statuses or ["ok"])
        self.calls: list[dict] = []

    def execute(self, **kwargs: object) -> str:
        """Record arguments and return the configured status."""
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self.statuses) - 1)
        return json.dumps({"status": self.statuses[index]})


def _drive(
    tool: BaseTool,
    run_dir: Path,
    batches: list[list[dict]],
) -> tuple[list[dict], list[dict]]:
    """Send argument batches through the real tool scheduling path."""
    registry = ToolRegistry()
    registry.register(tool)
    agent = AgentLoop(registry=registry, llm=SimpleNamespace(), max_iterations=4)
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)
    trace = TraceWriter(run_dir)
    messages: list[dict] = []
    react_trace: list[dict] = []
    call_number = 0
    for iteration, batch in enumerate(batches, start=1):
        tool_calls = []
        for arguments in batch:
            call_number += 1
            tool_calls.append(
                SimpleNamespace(
                    id=f"call_{call_number}",
                    name=tool.name,
                    arguments=arguments,
                )
            )
        agent._process_tool_calls(
            tool_calls,
            ContextBuilder,
            messages,
            trace,
            react_trace,
            iteration,
        )
    trace.close()
    return messages, list(TraceWriter.read(run_dir))


def test_legacy_metadata_maps_to_explicit_policies() -> None:
    """Legacy tool flags retain safe behavior under the new policy API."""
    readonly = _RecordingTool(is_readonly=True)
    mutation = _RecordingTool(is_readonly=False)
    readonly.deterministic = True

    assert readonly.effective_invocation_policy() == (InvocationPolicy.CACHE_IDENTICAL)
    readonly.deterministic = False
    assert readonly.effective_invocation_policy() == InvocationPolicy.ALLOW
    assert mutation.effective_invocation_policy() == InvocationPolicy.ONCE_PER_RUN


def test_once_per_run_mutation_blocks_same_batch_duplicate(tmp_path: Path) -> None:
    """A non-repeatable mutation is reserved before batch execution."""
    tool = _RecordingTool(is_readonly=False)

    messages, records = _drive(
        tool,
        tmp_path / "mutation",
        [[{"value": 1}, {"value": 2, "token": "secret-value"}]],
    )

    assert len(tool.calls) == 1
    assert len(messages) == 2
    skipped = [record for record in records if record["type"] == "tool_skipped"]
    assert len(skipped) == 1
    assert skipped[0]["invocation_policy"] == "once_per_run"
    assert skipped[0]["invocation_key"]
    assert skipped[0]["args"]["token"] == "[redacted]"


def test_once_per_run_failure_can_retry_next_iteration(tmp_path: Path) -> None:
    """Only a successful mutation closes the once-per-run policy."""
    tool = _RecordingTool(is_readonly=False, statuses=["error", "ok"])

    messages, records = _drive(
        tool,
        tmp_path / "retry",
        [[{"value": 1}], [{"value": 1}]],
    )

    assert len(tool.calls) == 2
    assert len(messages) == 2
    assert not [record for record in records if record["type"] == "tool_skipped"]
