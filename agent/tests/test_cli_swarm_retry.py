"""Regression tests for swarm retry and resume CLI entry points."""

from __future__ import annotations

import cli.commands.swarm_runtime as _cmd_swarm_runtime

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest


def test_swarm_retry_dispatches_full_retry_by_default() -> None:
    from cli.commands.common import EXIT_SUCCESS
    from cli.commands.dispatch import main

    with patch('cli.commands.swarm_runtime.cmd_swarm_retry_live', return_value=0) as retry:
        rc = main(["--swarm-retry", "run-123"])

    assert rc == EXIT_SUCCESS
    retry.assert_called_once_with("run-123", resume=False)


def test_swarm_retry_dispatches_resume_opt_in() -> None:
    from cli.commands.common import EXIT_SUCCESS
    from cli.commands.dispatch import main

    with patch('cli.commands.swarm_runtime.cmd_swarm_retry_live', return_value=0) as retry:
        rc = main(["--swarm-retry", "run-123", "--swarm-resume"])

    assert rc == EXIT_SUCCESS
    retry.assert_called_once_with("run-123", resume=True)


def test_swarm_resume_requires_retry_id(capsys: pytest.CaptureFixture[str]) -> None:
    from cli.commands.common import EXIT_USAGE_ERROR
    from cli.commands.dispatch import main

    rc = main(["--swarm-resume"])

    assert rc == EXIT_USAGE_ERROR
    assert "requires --swarm-retry" in capsys.readouterr().out


def test_swarm_retry_slash_command_accepts_resume_opt_in() -> None:
    from cli.commands.swarm import dispatch

    with patch('cli.commands.swarm_runtime.cmd_swarm_retry_live') as retry:
        dispatch("retry run-123 --resume")

    retry.assert_called_once_with("run-123", resume=True)


def test_swarm_retry_passes_prior_run_only_for_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pass

    captured: dict[str, object] = {}
    status = SimpleNamespace(running="running", failed="failed", cancelled="cancelled")
    prior = SimpleNamespace(
        id="run-failed",
        status=status.failed,
        preset_name="demo",
        user_vars={"ticker": "AAPL"},
    )

    class FakeStore:
        def __init__(self, *, base_dir) -> None:
            captured["base_dir"] = base_dir

        def load_run(self, run_id):
            assert run_id == "run-failed"
            return prior

        def reconcile_run(self, run, *, write):
            assert run is prior
            assert write is True
            return prior

    class FakeRuntime:
        def __init__(self, *, store, agent_config) -> None:
            captured["store"] = store
            captured["agent_config"] = agent_config

        def start_run(self, preset_name, variables, **kwargs):
            captured["preset_name"] = preset_name
            captured["variables"] = variables
            captured.update(kwargs)
            return SimpleNamespace(id="run-retry")

    swarm_package = ModuleType("src.swarm")
    swarm_package.__path__ = []  # type: ignore[attr-defined]
    models_module = ModuleType("src.swarm.models")
    models_module.RunStatus = status
    runtime_module = ModuleType("src.swarm.runtime")
    runtime_module.SwarmRuntime = FakeRuntime
    store_module = ModuleType("src.swarm.store")
    store_module.SwarmStore = FakeStore

    monkeypatch.setitem(sys.modules, "src.swarm", swarm_package)
    monkeypatch.setitem(sys.modules, "src.swarm.models", models_module)
    monkeypatch.setitem(sys.modules, "src.swarm.runtime", runtime_module)
    monkeypatch.setitem(sys.modules, "src.swarm.store", store_module)
    monkeypatch.setattr("src.config.load_swarm_agent_config", lambda: {"agents": []})
    monkeypatch.setattr(_cmd_swarm_runtime, "_watch_swarm_run", lambda *args: 0)

    assert _cmd_swarm_runtime.cmd_swarm_retry_live("run-failed", resume=True) == 0
    assert captured["preset_name"] == "demo"
    assert captured["resume_from"] is not None
    assert captured["resume_from"].id == "run-failed"


def test_swarm_dashboard_marks_resumed_task_as_kept() -> None:
    from cli.commands.swarm_runtime import _SwarmDashboard

    dashboard = _SwarmDashboard("demo", "run-retry")
    dashboard.handle_event(
        SimpleNamespace(
            agent_id="analyst",
            type="task_resumed",
            data={"source_run_id": "run-failed"},
        )
    )

    assert dashboard.agents["analyst"]["status"] == "resumed"
    assert dashboard.agents["analyst"]["tool"] == "kept"
