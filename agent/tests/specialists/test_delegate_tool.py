"""Tests for the delegate_to_specialist tool: execution, cancel, timeout,
thread hygiene, concurrency, and the recursion boundary."""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from unittest.mock import patch

import pytest

from src.agent.loop import AgentLoop
from src.specialists.loader import load_specialists, reset_specialists_cache
from src.specialists.models import SpecialistSpec
from src.tools import build_filtered_registry
from src.tools.delegate_tool import DelegateToSpecialistTool


@pytest.fixture(autouse=True)
def _fresh_roster():
    reset_specialists_cache()
    yield
    reset_specialists_cache()


class _FakeChatLLM:
    """Constructor-compatible ChatLLM stub (closed on finally, no I/O)."""

    closed = 0

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name

    def close(self) -> None:
        type(self).closed += 1


class _FakeLoop:
    """AgentLoop stand-in: records construction, finishes fast by default."""

    instances: list["_FakeLoop"] = []
    run_behavior = None  # optional callable(self, task) -> dict

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.registry = kwargs.get("registry")
        self.skills_loader = kwargs.get("skills_loader")
        self._cancel_event = threading.Event()
        self.cancel_called = 0
        type(self).instances.append(self)

    def cancel(self) -> None:
        self.cancel_called += 1
        self._cancel_event.set()

    def run(self, task: str, session_id: str = "") -> dict:
        behavior = type(self).run_behavior
        if behavior is not None:
            return behavior(self, task)
        return {
            "status": "ok",
            "content": f"finished: {task}",
            "run_dir": None,
            "iterations": 2,
        }


@pytest.fixture()
def fake_loop_class():
    _FakeLoop.instances = []
    _FakeLoop.run_behavior = None
    _FakeChatLLM.closed = 0
    with (
        patch("src.agent.loop.AgentLoop", _FakeLoop),
        patch("src.providers.chat.ChatLLM", _FakeChatLLM),
    ):
        yield _FakeLoop


def _spec(name: str = "quant-agent", timeout: int = 600) -> SpecialistSpec:
    return SpecialistSpec(
        name=name,
        description="test specialist",
        prompt="You are a test.",
        tools=["read_file"],
        skills=["alpha-zoo"],
        max_iterations=5,
        timeout_seconds=timeout,
    )


def _tool(roster: dict[str, SpecialistSpec]) -> DelegateToSpecialistTool:
    with patch("src.tools.delegate_tool.load_specialists", lambda: roster):
        return DelegateToSpecialistTool()


def _execute(
    tool: DelegateToSpecialistTool, roster: dict[str, SpecialistSpec], **kwargs: Any
) -> dict:
    """Run the tool against the fake roster and stubbed registry builder.

    Callers must hold no other patch of these module attributes: mock.patch is
    process-global, so per-thread patching corrupts the module binding (a
    thread that enters while another is active restores the *other* thread's
    lambda on exit). Concurrent tests therefore patch ONCE around all threads.
    """
    with (
        patch("src.tools.delegate_tool.load_specialists", lambda: roster),
        patch("src.tools.build_filtered_registry", lambda *a, **k: None),
    ):
        return json.loads(tool.execute(**kwargs))


class _patched_execution:
    """Context manager: patch the roster + registry builder once (thread-safe
    to share across threads, unlike nested per-thread patch calls)."""

    def __init__(self, roster: dict[str, SpecialistSpec]) -> None:
        self._stack = None
        self._roster = roster

    def __enter__(self):
        from contextlib import ExitStack

        self._stack = ExitStack()
        self._stack.enter_context(
            patch("src.tools.delegate_tool.load_specialists", lambda: self._roster)
        )
        self._stack.enter_context(
            patch("src.tools.build_filtered_registry", lambda *a, **k: None)
        )
        return self

    def __exit__(self, *exc):
        self._stack.close()
        return False


def test_successful_delegation_returns_self_contained_payload(fake_loop_class) -> None:
    roster = {"quant-agent": _spec()}
    tool = _tool(roster)
    payload = _execute(tool, roster, specialist="quant-agent", task="bench the zoo")
    assert payload["status"] == "ok"
    assert payload["specialist"] == "quant-agent"
    assert payload["content"].startswith("finished:")
    assert payload["iterations"] == 2
    assert payload["duration_s"] >= 0
    child = fake_loop_class.instances[0]
    assert child.kwargs["max_iterations"] == 5
    assert child.skills_loader is not None


def test_unknown_specialist_fails_closed_with_roster(fake_loop_class) -> None:
    roster = {"quant-agent": _spec()}
    tool = _tool(roster)
    payload = _execute(tool, roster, specialist="nope", task="x")
    assert payload["status"] == "error"
    assert payload["available_specialists"] == ["quant-agent"]
    assert fake_loop_class.instances == []


def test_empty_task_refused(fake_loop_class) -> None:
    roster = {"quant-agent": _spec()}
    tool = _tool(roster)
    payload = _execute(tool, roster, specialist="quant-agent", task="   ")
    assert payload["status"] == "error"
    assert fake_loop_class.instances == []


def test_parent_cancel_reaches_running_child(fake_loop_class) -> None:
    def _wait_for_cancel(self: _FakeLoop, task: str) -> dict:
        if self._cancel_event.wait(30):
            return {
                "status": "cancelled",
                "content": "",
                "run_dir": None,
                "iterations": 1,
            }
        return {
            "status": "ok",
            "content": "not cancelled",
            "run_dir": None,
            "iterations": 1,
        }

    fake_loop_class.run_behavior = _wait_for_cancel
    roster = {"quant-agent": _spec()}
    tool = _tool(roster)
    parent_cancel = threading.Event()
    tool.bind_parent(cancel_event=parent_cancel)

    outcome: dict[str, Any] = {}
    caller = threading.Thread(
        target=lambda: outcome.setdefault(
            "payload",
            _execute(tool, roster, specialist="quant-agent", task="long task"),
        ),
        name="test-caller",
        daemon=True,
    )
    started = time.monotonic()
    caller.start()
    time.sleep(0.3)  # let the child start
    parent_cancel.set()
    caller.join(10)
    elapsed = time.monotonic() - started
    assert not caller.is_alive(), "delegation did not return after parent cancel"
    assert elapsed < 10
    assert outcome["payload"]["status"] == "cancelled"
    assert fake_loop_class.instances[0].cancel_called >= 1


def test_budget_timeout_cancels_and_reports(fake_loop_class) -> None:
    release = threading.Event()

    def _wait(self: _FakeLoop, task: str) -> dict:
        release.wait(30)
        return {"status": "ok", "content": "late", "run_dir": None, "iterations": 1}

    fake_loop_class.run_behavior = _wait
    roster = {"quant-agent": _spec(timeout=1)}
    tool = _tool(roster)
    payload = _execute(tool, roster, specialist="quant-agent", task="slow task")
    assert payload["status"] == "timeout"
    assert "budget" in payload["error"]
    assert fake_loop_class.instances[0].cancel_called >= 1
    release.set()


def test_zombie_child_is_abandoned_and_reclaimed(
    fake_loop_class, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.tools.delegate_tool._CANCEL_GRACE_SECONDS", 0.2)
    release = threading.Event()

    def _never_stop(self: _FakeLoop, task: str) -> dict:
        release.wait(60)  # ignores cancel entirely — the stuck-tool case
        return {"status": "ok", "content": "", "run_dir": None, "iterations": 1}

    fake_loop_class.run_behavior = _never_stop
    roster = {"quant-agent": _spec(timeout=1)}
    tool = _tool(roster)
    started = time.monotonic()
    payload = _execute(tool, roster, specialist="quant-agent", task="stuck task")
    elapsed = time.monotonic() - started
    assert payload["status"] == "timeout"
    assert elapsed < 10, f"execute blocked for {elapsed:.1f}s"

    def _leaked() -> list[threading.Thread]:
        return [
            t
            for t in threading.enumerate()
            if t.name.startswith(
                ("specialist-quant-agent", "specialist-relay-quant-agent")
            )
        ]

    assert _leaked(), "expected the stuck child thread to still exist at return"
    release.set()
    deadline = time.monotonic() + 10
    while _leaked() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _leaked(), f"specialist threads leaked: {[t.name for t in _leaked()]}"
    assert _FakeChatLLM.closed >= 1  # transport closed under the zombie


def test_concurrent_delegations_on_one_instance_do_not_interfere(
    fake_loop_class,
) -> None:
    roster = {"quant-agent": _spec(), "web-docs-agent": _spec("web-docs-agent")}
    tool = _tool(roster)  # one shared instance, as the MCP registry would hold

    results: dict[str, dict] = {}
    # One process-global patch shared by both threads — never patch per-thread.
    with _patched_execution(roster):
        threads = [
            threading.Thread(
                target=lambda n=name: results.setdefault(
                    n, json.loads(tool.execute(specialist=n, task=f"task for {n}"))
                ),
                daemon=True,
            )
            for name in roster
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
    assert set(results) == set(roster)
    for name, payload in results.items():
        assert payload["status"] == "ok"
        assert payload["specialist"] == name
        assert name in payload["content"]


def test_child_registry_is_whitelist_projected_without_delegation() -> None:
    """The child surface: whitelisted tools present, no delegate tool, no
    shell family, load_skill restricted to the specialist's skills."""
    spec = load_specialists()["quant-agent"]
    registry = build_filtered_registry(
        spec.tools, include_shell_tools=False, skill_allowlist=spec.skills
    )
    names = set(registry.tool_names)
    assert set(spec.tools) <= names
    assert "delegate_to_specialist" not in names
    assert "run_swarm" not in names
    assert not names.intersection({"bash", "background_run", "cancel_background"})
    loader_tool = registry.get("load_skill")
    assert loader_tool is not None
    refused = json.loads(loader_tool.execute(name="doc-reader"))
    assert refused["status"] == "error"
    assert json.loads(loader_tool.execute(name="alpha-zoo"))["status"] == "ok"


def test_gate_off_excludes_tool_from_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config.accessor import reset_env_config

    monkeypatch.setenv("VIBE_TRADING_SPECIALISTS_ENABLED", "0")
    reset_env_config()
    try:
        from src.tools import build_registry

        assert build_registry().get("delegate_to_specialist") is None
    finally:
        reset_env_config()


def test_gate_on_registers_tool_with_event_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.config.accessor import reset_env_config

    monkeypatch.setenv("VIBE_TRADING_SPECIALISTS_ENABLED", "1")
    reset_env_config()
    try:
        from src.tools import build_registry

        tool = build_registry(event_callback=lambda *a: None).get(
            "delegate_to_specialist"
        )
        assert tool is not None
        assert tool._event_callback is not None
        # The schema enum advertises exactly the loaded roster.
        enum = tool.parameters["properties"]["specialist"]["enum"]
        assert set(enum) == set(load_specialists())
    finally:
        reset_env_config()


def test_events_emitted_when_callback_present(fake_loop_class) -> None:
    roster = {"quant-agent": _spec()}
    events: list[tuple[str, dict]] = []
    with patch("src.tools.delegate_tool.load_specialists", lambda: roster):
        tool = DelegateToSpecialistTool(
            event_callback=lambda t, d: events.append((t, d))
        )
    _execute(tool, roster, specialist="quant-agent", task="x")
    kinds = [k for k, _ in events]
    assert kinds == ["subagent_started", "subagent_completed"]
    assert events[1][1]["specialist"] == "quant-agent"
    assert events[1][1]["status"] == "ok"


def test_agent_loop_binds_parent_cancel() -> None:
    """AgentLoop construction wires its cancel event into the delegate tool
    (bind_parent), which is what lets a user stop reach a running specialist."""
    from src.tools import build_registry

    roster = {"quant-agent": _spec()}

    class _StubLLM:
        runtime_snapshot = None
        model_name = "test"

    with (
        patch("src.tools.delegate_tool.load_specialists", lambda: roster),
        patch.dict("os.environ", {"VIBE_TRADING_SPECIALISTS_ENABLED": "1"}),
    ):
        from src.config.accessor import reset_env_config

        reset_env_config()
        try:
            registry = build_registry()
            assert registry.get("delegate_to_specialist") is not None
            loop = AgentLoop(registry=registry, llm=_StubLLM())
            tool = registry.get("delegate_to_specialist")
            assert tool._parent_cancel is loop._cancel_event
        finally:
            reset_env_config()
