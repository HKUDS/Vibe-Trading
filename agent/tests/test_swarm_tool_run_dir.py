"""The swarm worker must confine a tool-declared ``run_dir`` to the agent workspace.

A tool that declares ``run_dir`` is being *pointed* at a directory by the model.
The worker used to overwrite that value with the agent's workspace root, so the
argument could never take effect: on a real run the strategist passed ten paths
that were all discarded and every backtest failed with ``config.json not found``.
The value is now honoured, but confined to the workspace — the argument decides
which run's files a tool reads and writes, so it is not allowed to leave the
agent's own sandbox.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.swarm.worker as worker_mod
from src.agent.tools import BaseTool, ToolRegistry
from src.providers.chat import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmTask
from src.swarm.worker import _tool_arguments, run_worker


class _DeclaredTool(BaseTool):
    """Declares ``run_dir`` — like backtest, pattern, scaffold_signal_engine."""

    name = "declared_probe"
    description = "Probe that takes a run_dir."
    parameters = {
        "type": "object",
        "properties": {"run_dir": {"type": "string"}},
        "required": ["run_dir"],
    }
    received: list[str] = []

    def execute(self, **kwargs) -> str:
        type(self).received.append(str(kwargs.get("run_dir")))
        return '{"status": "ok"}'


class _WorkspaceTool(BaseTool):
    """Does not declare ``run_dir`` — like write_file, read_file, bash."""

    name = "workspace_probe"
    description = "Probe that expects the workspace."
    parameters = {"type": "object", "properties": {}}
    received: list[str] = []

    def execute(self, **kwargs) -> str:
        type(self).received.append(str(kwargs.get("run_dir")))
        return '{"status": "ok"}'


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "artifacts" / "analyst"
    ws.mkdir(parents=True)
    return ws


def test_undeclared_run_dir_is_pinned_to_the_workspace(workspace: Path) -> None:
    """The workspace is the file tools' confinement root — the model must not pick it."""
    args, refusal = _tool_arguments(_WorkspaceTool(), {}, workspace)

    assert refusal is None
    assert args["run_dir"] == str(workspace)
    # and a stray value cannot redirect a workspace-scoped tool
    args, _ = _tool_arguments(
        _WorkspaceTool(), {"run_dir": "/tmp/elsewhere"}, workspace
    )
    assert args["run_dir"] == str(workspace)


def test_relative_run_dir_resolves_under_the_workspace(workspace: Path) -> None:
    """The regression: a relative path the agent created must reach the tool."""
    args, refusal = _tool_arguments(
        _DeclaredTool(), {"run_dir": "runs/demo"}, workspace
    )

    assert refusal is None
    assert args["run_dir"] == str(workspace / "runs" / "demo")


def test_absolute_run_dir_inside_the_workspace_is_honoured(workspace: Path) -> None:
    inside = str(workspace / "runs" / "demo")

    args, refusal = _tool_arguments(_DeclaredTool(), {"run_dir": inside}, workspace)

    assert refusal is None
    assert args["run_dir"] == inside


def test_blank_run_dir_falls_back_to_the_workspace(workspace: Path) -> None:
    args, refusal = _tool_arguments(_DeclaredTool(), {"run_dir": "   "}, workspace)

    assert refusal is None
    assert args["run_dir"] == str(workspace)


@pytest.mark.parametrize(
    "escaping",
    ["/tmp/elsewhere", "../sibling_agent", "../../..", "runs/../../escape"],
)
def test_run_dir_outside_the_workspace_is_refused(
    workspace: Path, escaping: str
) -> None:
    """Refused, not silently swapped: the substitution is what hid the real bug."""
    args, refusal = _tool_arguments(_DeclaredTool(), {"run_dir": escaping}, workspace)

    assert refusal is not None
    assert str(workspace) in refusal, "the refusal must name the workspace boundary"
    assert "outside this agent's workspace" in refusal


class _ScriptedLLM:
    def __init__(self, tool_name: str, arguments: dict) -> None:
        self._responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="c1", name=tool_name, arguments=arguments)
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="Completed the probe with a clear, substantive conclusion.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]

    def stream_chat(self, messages, tools=None, timeout=None, on_text_chunk=None):
        return self._responses.pop(0)

    def close(self) -> None:
        """No-op: the scripted stub owns no HTTP client."""


def _run_worker_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: BaseTool, arguments: dict
):
    registry = ToolRegistry()
    registry.register(tool)
    monkeypatch.setattr(
        worker_mod, "build_swarm_registry", lambda *args, **kwargs: registry
    )
    monkeypatch.setattr(
        worker_mod,
        "ChatLLM",
        lambda *args, **kwargs: _ScriptedLLM(tool.name, arguments),
    )
    events = []
    run_worker(
        agent_spec=SwarmAgentSpec(
            id="analyst",
            role="Analyst",
            system_prompt="Run the probe.",
            tools=[tool.name],
            max_iterations=3,
        ),
        task=SwarmTask(id="task", agent_id="analyst", prompt_template="Run the probe."),
        upstream_summaries={},
        user_vars={},
        run_dir=tmp_path,
        event_callback=events.append,
    )
    return events


def test_worker_passes_a_relative_run_dir_through_to_the_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The call site, not only the helper: this is where the value was discarded."""
    _DeclaredTool.received.clear()

    _run_worker_with(tmp_path, monkeypatch, _DeclaredTool(), {"run_dir": "runs/demo"})

    assert _DeclaredTool.received == [
        str(tmp_path / "artifacts" / "analyst" / "task" / "runs" / "demo")
    ]


def test_worker_refuses_an_escaping_run_dir_without_calling_the_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An escape must surface as a tool error, so the agent can correct it."""
    _DeclaredTool.received.clear()

    events = _run_worker_with(
        tmp_path, monkeypatch, _DeclaredTool(), {"run_dir": "../../other_run"}
    )

    assert _DeclaredTool.received == [], "the tool must not run on an unusable run_dir"
    results = [e for e in events if e.type == "tool_result"]
    assert results and results[0].data["status"] == "error"
    assert "workspace" in json.dumps(results[0].data["result_preview"])
