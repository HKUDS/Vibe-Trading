"""Parallel tool calls run in a copy of the submitting thread's context.

A read-only batch runs on a thread pool. Without a context copy each worker
starts from an empty context, so a tool that calls an LLM inside the batch
sends no provider session id (OpenCode Go requires it, #1416).
"""

from __future__ import annotations

import contextvars
import json
import threading
from pathlib import Path
from types import SimpleNamespace

from src.agent.runtime import AgentRuntime
from src.agent.tools import BaseTool, ToolRegistry
from src.config.accessor import get_env_config
from src.kernel.contracts import BoundCall
from src.kernel.tool_runner import execute_batch
from src.product.context import ContextBuilder
from src.product.tool_policy import ToolPolicy
from src.providers.session_context import (
    bind_llm_session_id,
    current_llm_session_id,
    reset_llm_session_id,
)
from tests.recording_helpers import recorder_at, run_recorded_tools


class _SessionProbe(BaseTool):
    """Read-only tool that records the provider session id it observes."""

    name = "session_probe"
    description = "records the bound LLM session id"
    parameters: dict = {"type": "object", "properties": {"i": {"type": "integer"}}}
    repeatable = True
    is_readonly = True

    def __init__(self, observed: list[str]) -> None:
        self.observed = observed

    def execute(self, **kwargs: object) -> str:
        self.observed.append(current_llm_session_id())
        return json.dumps({"status": "ok", "i": kwargs.get("i")})


def test_parallel_tools_keep_the_parent_session_context(tmp_path: Path) -> None:
    observed: list[str] = []
    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(_SessionProbe(observed))
    agent = AgentRuntime(registry=registry, llm=SimpleNamespace(), max_iterations=2,
                         event_callback=lambda name, data: None)
    agent.memory.run_dir = str(tmp_path)
    trace = recorder_at(tmp_path)
    calls = [SimpleNamespace(id=f"call_{i}", name="session_probe", arguments={"i": i}) for i in range(2)]

    token = bind_llm_session_id("shared-session")
    try:
        run_recorded_tools(agent, calls, ContextBuilder, [], trace, 1)
    finally:
        reset_llm_session_id(token)
        trace.close()

    assert observed == ["shared-session", "shared-session"]
    assert current_llm_session_id() == ""


def test_each_parallel_call_gets_its_own_context_copy() -> None:
    var: contextvars.ContextVar[str] = contextvars.ContextVar("probe", default="")
    var.set("parent")
    barrier = threading.Barrier(2, timeout=5)
    seen: dict[int, tuple[str, str]] = {}
    results: dict[int, tuple[str, int]] = {}

    def bound(index: int) -> BoundCall:
        def invoke() -> tuple[str, int]:
            inherited = var.get()
            var.set(f"call-{index}")
            barrier.wait()  # both calls are inside their contexts at once
            seen[index] = (inherited, var.get())
            return "{}", 0

        return BoundCall(start=lambda in_parallel: invoke,
                         finish=lambda result, ms: results.setdefault(index, (result, ms)),
                         skip=lambda: None, parallel=True)

    execute_batch([bound(0), bound(1)], lambda: False)

    assert seen == {0: ("parent", "call-0"), 1: ("parent", "call-1")}
    assert var.get() == "parent"
    assert set(results) == {0, 1}
