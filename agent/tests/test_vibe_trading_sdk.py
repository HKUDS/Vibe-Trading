"""The embeddable ``vibe_trading`` facade over SessionService.

Runs go through the real SessionService and the real AgentLoop; only the
provider (a scripted LLM), the tool registry (one offline tool) and the search
index are replaced, the way the session-service tests already do it.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

import vibe_trading
from src.agent.tools import BaseTool, ToolRegistry
from vibe_trading import (
    Client,
    ClientClosedError,
    ClientSettings,
    ReasoningDelta,
    RunCancelled,
    RunCompleted,
    RunFailed,
    RunStarted,
    RuntimeRootInUseError,
    SessionBusyError,
    SessionNotFoundError,
    TextDelta,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)
from vibe_trading._mapping import EVENT_TABLE, translate

AGENT_DIR = Path(__file__).resolve().parents[1]
ROOT = AGENT_DIR.parent

DOCUMENTED_NAMES = {
    "Client", "ClientClosedError", "ClientSettings", "Event", "MessageInfo",
    "ReasoningDelta", "RunCancelled", "RunCompleted", "RunFailed", "RunResult",
    "RunStarted", "RuntimeRootInUseError", "SessionBusyError", "SessionInfo",
    "register_tool",
    "SessionNotFoundError", "Stream", "TextDelta", "ToolCompleted", "ToolFailed",
    "ToolStarted",
}


class _ProbeTool(BaseTool):
    """Offline tool; the required constructor argument keeps it out of discovery."""

    name = "sdk_probe"
    description = "Offline probe (test double)."
    parameters = {"type": "object", "properties": {"mode": {"type": "string"}}}
    is_readonly = True
    repeatable = True

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def execute(self, **kwargs: Any) -> str:
        mode = str(kwargs.get("mode"))
        self.calls.append(mode)
        if mode == "fail":
            return json.dumps({"status": "error", "error": "probe failed"})
        return json.dumps({"status": "ok", "value": "probe ok"})


def _call(call_id: str, mode: str) -> SimpleNamespace:
    return SimpleNamespace(id=call_id, name="sdk_probe", arguments={"mode": mode})


def _reply(content: str = "", tool_calls: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        reasoning_content=None,
        has_tool_calls=bool(tool_calls),
        tool_calls=tool_calls or [],
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        response_model="scripted-model-001",
    )


class _ScriptedLLM:
    """Replays one step per model call; a step is a callable of the callbacks."""

    model_name = "scripted-model"

    def __init__(self, steps: list[Callable[..., SimpleNamespace]]) -> None:
        self.steps = list(steps)

    def stream_chat(self, messages: list, **kwargs: Any) -> SimpleNamespace:
        del messages
        return self.steps.pop(0)(**kwargs)

    def chat(self, messages: list, **kwargs: Any) -> SimpleNamespace:  # compaction
        del messages, kwargs
        return _reply("summary")

    async def aclose(self) -> None:
        return None


class _DummyIndex:
    def index_session(self, session_id: str, title: str) -> None:
        del session_id, title

    def index_message(self, session_id: str, role: str, content: str) -> None:
        del session_id, role, content

    def remove_session(self, session_id: str) -> None:
        del session_id


@pytest.fixture
def kernel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Point the kernel at a temp root and script its provider and tools."""
    from src.agent import loop as agent_loop

    root = tmp_path / "vt-home"
    monkeypatch.setattr(agent_loop, "RUNS_DIR", root / "runs")
    monkeypatch.setattr(agent_loop, "SESSIONS_DIR", root / "sessions")
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    state = SimpleNamespace(root=root, scripts=[], tool_calls=[], registry_args=[])

    def _chat_llm() -> _ScriptedLLM:
        return _ScriptedLLM(state.scripts.pop(0))

    def _build_registry(**kwargs: Any) -> ToolRegistry:
        state.registry_args.append(kwargs)
        registry = ToolRegistry()
        registry.register(_ProbeTool(state.tool_calls))
        return registry

    monkeypatch.setattr("src.providers.chat.ChatLLM", _chat_llm)
    monkeypatch.setattr("src.tools.build_registry", _build_registry)
    return state


def _tool_then_answer(**kwargs: Any) -> list:
    """Reasoning, a succeeding call, a failing call, then a streamed answer."""

    def first(on_reasoning_chunk, **_: Any) -> SimpleNamespace:
        on_reasoning_chunk("checking the probe")
        return _reply(tool_calls=[_call("c1", "ok")])

    def second(**_: Any) -> SimpleNamespace:
        return _reply(tool_calls=[_call("c2", "fail")])

    def third(on_text_chunk, **_: Any) -> SimpleNamespace:
        on_text_chunk("All ")
        on_text_chunk("done.")
        return _reply("All done.")

    return [first, second, third]


def _run(coro):
    return asyncio.run(coro)


def test_run_end_to_end_returns_the_stored_answer(kernel) -> None:
    kernel.scripts.append(_tool_then_answer())

    async def scenario():
        async with Client() as client:
            result = await client.run("Probe it", title="sdk")
            messages = await client.get_messages(result.session_id)
            sessions = await client.list_sessions()
            return result, messages, sessions

    result, messages, sessions = _run(scenario())

    assert result.status == "completed"
    assert result.text == "All done."
    assert result.error is None
    assert result.model == "scripted-model-001"
    assert result.provider
    assert result.run_dir and Path(result.run_dir).parent == kernel.root / "runs"
    assert result.usage is not None
    assert result.usage["calls"] == 3
    assert result.usage["total_tokens"] == 45
    assert result.elapsed_ms is not None and result.elapsed_ms >= 0
    assert kernel.tool_calls == ["ok", "fail"]
    assert [(m.role, m.content) for m in messages] == [("user", "Probe it"), ("assistant", "All done.")]
    assert messages[1].attempt_id == result.attempt_id
    assert messages[1].metadata["status"] == "completed"
    assert [s.session_id for s in sessions] == [result.session_id]
    assert sessions[0].title == "sdk"
    # Shell tools default off and reach build_registry through the service.
    assert kernel.registry_args[0]["include_shell_tools"] is False


def test_events_are_mapped_in_order_and_unknown_ones_dropped(kernel) -> None:
    kernel.scripts.append(_tool_then_answer())

    async def scenario():
        async with Client() as client:
            session = await client.create_session()
            stream = await client.send(session.session_id, "Probe it")
            events = [event async for event in stream]
            return events, await stream.wait(), stream

    events, result, stream = _run(scenario())

    assert [type(e) for e in events] == [
        RunStarted,
        ReasoningDelta,
        ToolStarted,
        ToolCompleted,
        ToolStarted,
        ToolFailed,
        TextDelta,
        TextDelta,
        RunCompleted,
    ]
    assert {e.attempt_id for e in events} == {stream.attempt_id}
    assert {e.session_id for e in events} == {stream.session_id}
    reasoning, started, completed, started2, failed = events[1:6]
    assert reasoning.text == "checking the probe" and reasoning.chars == len("checking the probe")
    assert (started.tool, started.call_id, started.arguments["mode"]) == ("sdk_probe", "c1", "ok")
    assert completed.call_id == "c1" and "probe ok" in completed.preview
    assert started2.call_id == "c2" and failed.call_id == "c2" and "probe failed" in failed.preview
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "All done."
    assert events[-1].result == result
    assert events[-1].type == "run.completed"


def test_model_failure_ends_with_run_failed(kernel) -> None:
    def boom(**_: Any) -> SimpleNamespace:
        raise RuntimeError("provider exploded")

    kernel.scripts.append([boom])

    async def scenario():
        async with Client() as client:
            session = await client.create_session()
            stream = await client.send(session.session_id, "Fail please")
            return [event async for event in stream], await stream.wait()

    events, result = _run(scenario())

    assert isinstance(events[0], RunStarted)
    assert isinstance(events[-1], RunFailed)
    assert result.status == "failed"
    assert result.error
    assert result.text.startswith("Execution failed")


def _wait_until(flag: Callable[[], bool], seconds: float = 20.0) -> None:
    """Block the model thread until ``flag`` holds, bounded so a bug cannot hang."""
    deadline = time.monotonic() + seconds
    while not flag() and time.monotonic() < deadline:
        time.sleep(0.01)


def test_cancel_stops_the_run_and_a_finished_stream_cannot_cancel_a_later_run(kernel) -> None:
    release = threading.Event()

    def until_cancelled(on_text_chunk, should_cancel, **_: Any) -> SimpleNamespace:
        on_text_chunk("working")
        _wait_until(should_cancel)
        return _reply("partial")

    def until_released(on_text_chunk, should_cancel, **_: Any) -> SimpleNamespace:
        on_text_chunk("second")
        _wait_until(lambda: release.is_set() or should_cancel())
        return _reply("second done")

    kernel.scripts.extend([[until_cancelled], [until_released]])

    async def scenario():
        async with Client() as client:
            session = await client.create_session()
            first = await client.send(session.session_id, "Run long")
            seen = []
            async for event in first:
                seen.append(event)
                if isinstance(event, TextDelta):
                    assert await first.cancel() is True
            first_result = await first.wait()

            # The same session's next run: the finished handle must not stop it.
            second = await client.send(session.session_id, "Run again")
            late_cancel = None
            async for event in second:
                if isinstance(event, TextDelta) and late_cancel is None:
                    late_cancel = await first.cancel()
                    release.set()
            return seen, first_result, late_cancel, await second.wait()

    seen, first_result, late_cancel, second_result = _run(scenario())

    assert isinstance(seen[-1], RunCancelled)
    assert first_result.status == "cancelled"
    assert late_cancel is False
    assert second_result.status == "completed"
    assert second_result.text == "second done"


def test_two_sessions_run_concurrently_without_crossing_events(kernel) -> None:
    def answer(text: str) -> list:
        def step(on_text_chunk, **_: Any) -> SimpleNamespace:
            on_text_chunk(text)
            return _reply(text)

        return [step]

    kernel.scripts.extend([answer("alpha answer"), answer("beta answer")])

    async def scenario():
        async with Client() as client:
            a = await client.create_session(title="a")
            b = await client.create_session(title="b")
            stream_a = await client.send(a.session_id, "first")
            stream_b = await client.send(b.session_id, "second")
            with pytest.raises(SessionBusyError):
                await client.send(a.session_id, "again")
            events_a, events_b = await asyncio.gather(
                _collect(stream_a), _collect(stream_b)
            )
            return a, b, events_a, events_b, await client.list_sessions()

    a, b, events_a, events_b, sessions = _run(scenario())

    assert {e.session_id for e in events_a} == {a.session_id}
    assert {e.session_id for e in events_b} == {b.session_id}
    texts = {events_a[-1].result.text, events_b[-1].result.text}
    assert texts == {"alpha answer", "beta answer"}
    assert {s.session_id for s in sessions} == {a.session_id, b.session_id}


def test_a_stream_ignores_events_of_other_sessions_and_attempts(kernel) -> None:
    release = threading.Event()

    def until_released(on_text_chunk, should_cancel, **_: Any) -> SimpleNamespace:
        on_text_chunk("own")
        _wait_until(lambda: release.is_set() or should_cancel())
        return _reply("own")

    kernel.scripts.append([until_released])

    async def scenario():
        async with Client() as client:
            session = await client.create_session()
            stream = await client.send(session.session_id, "Run")
            bus = client._service.event_bus
            texts = []
            async for event in stream:
                if isinstance(event, TextDelta):
                    texts.append(event.text)
                    if not release.is_set():
                        # Same attempt id under another session, and another
                        # attempt of this session: neither belongs to the stream.
                        bus.emit("other-session", 'item.delta', {"kind": 'text.delta', 'delta': 'leak-a', 'attempt_id': stream.attempt_id})
                        bus.emit(session.session_id, 'item.delta', {"kind": 'text.delta', 'delta': 'leak-b', 'attempt_id': 'another-attempt'})
                        await asyncio.sleep(0.05)
                        release.set()
            return texts

    assert _run(scenario()) == ["own"]


async def _collect(stream) -> list:
    return [event async for event in stream]


def test_sessions_can_be_deleted_and_missing_ones_are_named(kernel) -> None:
    async def scenario():
        async with Client() as client:
            session = await client.create_session()
            deleted = await client.delete_session(session.session_id)
            with pytest.raises(SessionNotFoundError):
                await client.get_messages(session.session_id)
            with pytest.raises(SessionNotFoundError):
                await client.send(session.session_id, "hello")
            return deleted, await client.delete_session(session.session_id), await client.list_sessions()

    deleted, deleted_again, sessions = _run(scenario())
    assert deleted is True and deleted_again is False and sessions == []


def test_one_client_per_runtime_root(kernel, monkeypatch) -> None:
    async def scenario():
        first = Client()
        with pytest.raises(RuntimeRootInUseError):
            Client(ClientSettings(runtime_root=kernel.root))
        assert await first.aclose() == []
        with pytest.raises(ClientClosedError):
            await first.create_session()
        second = Client(ClientSettings(runtime_root=kernel.root))
        await second.aclose()

    _run(scenario())

    with pytest.raises(ValueError, match="kernel's runtime root"):
        Client(ClientSettings(runtime_root=kernel.root.parent / "elsewhere"))

    # The HTTP server's own service on the same root is an owner too.
    import src.api.state as api_state

    fake_service = SimpleNamespace(store=SimpleNamespace(base_dir=kernel.root / "sessions"))
    monkeypatch.setattr(api_state, "_session_service", fake_service)
    with pytest.raises(RuntimeRootInUseError, match="HTTP server"):
        Client()


def test_closing_under_an_open_run_fails_its_stream(kernel) -> None:
    def blocking(should_cancel, **_: Any) -> SimpleNamespace:
        _wait_until(should_cancel)
        return _reply("late")

    kernel.scripts.append([blocking])

    async def scenario():
        client = Client()
        session = await client.create_session()
        stream = await client.send(session.session_id, "Run long")
        await asyncio.sleep(0.05)
        await client.aclose(timeout=5.0)
        with pytest.raises(ClientClosedError):
            await asyncio.wait_for(stream.wait(), timeout=20)
        assert stream.done

    _run(scenario())


def test_translate_drops_names_outside_the_vocabulary() -> None:
    for internal in ("llm_usage", "tool_progress", "tool_heartbeat", "compact",
                     "message.received", "attempt.created", "mcp.warning", "goal.updated"):
        assert internal not in EVENT_TABLE
        assert translate(internal, "s", "a", {"attempt_id": "a"}) is None
    assert set(EVENT_TABLE) == {
        "run.started", "item.delta:text.delta", "item.delta:text.reset",
        "item.delta:reasoning.delta", "item.started:tool.started",
        "item.completed:tool.completed", "item.completed:tool.failed",
        "run.completed", "run.failed", "run.cancelled",
    }
    # The table is keyed by the event envelope and item kind, so each sample
    # must be explicit when a name is reused with different item payloads.
    sample_values = [
        ("run.started", {}),
        ("item.delta", {"kind": "text.delta", "delta": "x"}),
        ("item.delta", {"kind": "text.reset"}),
        ("item.delta", {"kind": "reasoning.delta", "tail": "t", "chars": 1}),
        ("item.started", {"kind": "tool.started", "item": {"name": "t"}}),
        ("item.completed", {"kind": "tool.completed", "item": {"name": "t", "status": "ok"}}),
        ("item.completed", {"kind": "tool.failed", "item": {"name": "t", "status": "error"}}),
        ("run.completed", {}), ("run.failed", {}), ("run.cancelled", {}),
    ]
    produced = {translate(name, "s", "a", data).type for name, data in sample_values}
    assert produced == {
        "run.started", "text.delta", "reasoning.delta", "tool.started", "tool.completed",
        "tool.failed", "run.completed", "run.failed", "run.cancelled",
    }
    reset = translate("item.delta", "s", "a", {"kind": "text.reset"})
    assert isinstance(reset, TextDelta) and reset.reset is True and reset.text == ""


def test_public_surface_is_exactly_the_documented_names() -> None:
    assert set(vibe_trading.__all__) == DOCUMENTED_NAMES
    assert len(vibe_trading.__all__) == len(DOCUMENTED_NAMES)
    for name in vibe_trading.__all__:
        assert getattr(vibe_trading, name) is not None
    for internal in ("AgentLoop", "SessionService", "ToolRegistry", "build_registry"):
        assert not hasattr(vibe_trading, internal)


def test_installed_style_import_resolves_its_own_src(tmp_path: Path) -> None:
    conflicting = tmp_path / "another-project"
    (conflicting / "src").mkdir(parents=True)
    (conflicting / "src/__init__.py").write_text("raise RuntimeError('wrong project src imported')\n")
    home = tmp_path / "home"
    (home / ".vibe-trading").mkdir(parents=True)
    env = {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        VIBE_TRADING_HOME=str(home / ".vibe-trading"),
        PYTHONPATH=os.pathsep.join([str(conflicting), str(AGENT_DIR)]),
    )
    script = (
        "import json, vibe_trading, src;"
        "from vibe_trading import Client, RunResult, TextDelta;"
        "print(json.dumps([src.__file__, sorted(vibe_trading.__all__)]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    src_file, names = json.loads(result.stdout.strip().splitlines()[-1])
    assert Path(src_file).resolve() == (AGENT_DIR / "src/__init__.py").resolve()
    assert set(names) == DOCUMENTED_NAMES


def test_setuptools_find_includes_the_package_and_keeps_the_console_script() -> None:
    from setuptools import find_packages

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    find = pyproject["tool"]["setuptools"]["packages"]["find"]
    packages = find_packages(where=str(ROOT / find["where"][0]), include=find["include"])
    assert "vibe_trading" in packages
    assert {"src", "backtest", "cli", "evals"} <= set(packages)
    assert pyproject["project"]["scripts"]["vibe-trading"] == "cli:main"
    assert "py.typed" in pyproject["tool"]["setuptools"]["package-data"]["vibe_trading"]
    assert (AGENT_DIR / "vibe_trading" / "py.typed").is_file()


_HOLD_SCRIPT = (
    "import sys\n"
    "from src.session.runtime_lock import claim_sessions_dir\n"
    "claim_sessions_dir(sys.argv[1], 'a test process')\n"
    "print('held', flush=True)\n"
    "sys.stdin.read()\n"
)


def _hold_in_another_process(sessions_dir: Path, tmp_path: Path) -> subprocess.Popen:
    env = {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}
    env.update(HOME=str(tmp_path), VIBE_TRADING_HOME=str(tmp_path / "other-home"), PYTHONPATH=str(AGENT_DIR))
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLD_SCRIPT, str(sessions_dir)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    line = holder.stdout.readline().strip()
    assert line == "held", holder.stderr.read()
    return holder


def _release_holder(holder: subprocess.Popen) -> None:
    holder.stdin.close()
    holder.wait(timeout=60)


def test_another_process_on_the_root_is_refused_and_its_runs_are_left_alone(
    kernel, tmp_path, monkeypatch
) -> None:
    from src.session.models import Attempt, AttemptStatus, Session
    from src.session.runtime_lock import HTTP_SERVER_OWNER, SessionsDirInUseError, release_sessions_dir
    from src.session.store import SessionStore

    import api_server

    sessions_dir = kernel.root / "sessions"
    store = SessionStore(base_dir=sessions_dir)
    session = Session(title="served elsewhere")
    store.create_session(session)
    attempt = Attempt(session_id=session.session_id, prompt="in flight")
    attempt.mark_running()
    store.create_attempt(attempt)

    monkeypatch.setattr(api_server, "_session_service", None)
    monkeypatch.setattr(api_server, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(api_server, "RUNS_DIR", kernel.root / "runs")
    holder = _hold_in_another_process(sessions_dir, tmp_path)
    try:
        with pytest.raises(RuntimeRootInUseError, match="another process"):
            Client()
        # `vibe-trading serve` in this process is refused the same way.
        with pytest.raises(SessionsDirInUseError, match="another process"):
            api_server._get_session_service()
        assert store.get_attempt(session.session_id, attempt.attempt_id).status == AttemptStatus.RUNNING
    finally:
        _release_holder(holder)
        release_sessions_dir(sessions_dir, HTTP_SERVER_OWNER)

    async def scenario():
        async with Client():
            pass

    _run(scenario())  # The exited process's lock is gone with it.


def test_a_client_and_the_http_servers_service_exclude_each_other(kernel, monkeypatch) -> None:
    from src.session.runtime_lock import HTTP_SERVER_OWNER, SessionsDirInUseError, release_sessions_dir

    import api_server

    sessions_dir = kernel.root / "sessions"
    monkeypatch.setattr(api_server, "_session_service", None)
    monkeypatch.setattr(api_server, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(api_server, "RUNS_DIR", kernel.root / "runs")

    async def scenario():
        client = Client()
        # The server builds its service lazily, after the client took the root.
        with pytest.raises(SessionsDirInUseError, match="vibe_trading.Client"):
            api_server._get_session_service()
        await client.aclose()

    try:
        _run(scenario())
        assert api_server._get_session_service() is not None
        monkeypatch.setattr(api_server, "_session_service", None)
        # Rebuilding the server's own service on its root is not a conflict.
        assert api_server._get_session_service() is not None
        with pytest.raises(RuntimeRootInUseError):
            Client()
    finally:
        release_sessions_dir(sessions_dir, HTTP_SERVER_OWNER)


@pytest.mark.parametrize("bad_id", ["../x", "a/b", "", "x" * 129, "..", "id with space"])
def test_unsafe_session_ids_are_refused_before_touching_storage(kernel, bad_id) -> None:
    async def scenario():
        async with Client() as client:
            for call in (
                lambda: client.get_messages(bad_id),
                lambda: client.send(bad_id, "hello"),
                lambda: client.delete_session(bad_id),
            ):
                with pytest.raises(ValueError, match="invalid session_id"):
                    await call()

    _run(scenario())
    assert not (kernel.root / "x").exists()
    assert sorted(p.name for p in kernel.root.iterdir()) == ["sessions"]


def test_message_size_follows_the_http_route_limit(kernel) -> None:
    from src.session.input_rules import MAX_MESSAGE_CHARS

    def answer(**_: Any) -> SimpleNamespace:
        return _reply("ok")

    kernel.scripts.append([answer])

    async def scenario():
        async with Client() as client:
            session = await client.create_session()
            for text in ("", "x" * (MAX_MESSAGE_CHARS + 1)):
                with pytest.raises(ValueError, match="Message must contain"):
                    await client.send(session.session_id, text)
            assert await client.get_messages(session.session_id) == []
            stream = await client.send(session.session_id, "x" * MAX_MESSAGE_CHARS)
            return await stream.wait()

    assert _run(scenario()).status == "completed"


@pytest.mark.parametrize(("env_value", "expected"), [(None, False), ("0", False), ("1", True)])
def test_shell_tools_also_need_the_operators_switch(kernel, monkeypatch, env_value, expected) -> None:
    from src.config.accessor import reset_env_config

    if env_value is None:
        monkeypatch.delenv("VIBE_TRADING_ENABLE_SHELL_TOOLS", raising=False)
    else:
        monkeypatch.setenv("VIBE_TRADING_ENABLE_SHELL_TOOLS", env_value)
    reset_env_config()
    kernel.scripts.append([lambda **_: _reply("ok")])

    async def scenario():
        async with Client(ClientSettings(include_shell_tools=True)) as client:
            return await client.run("hi")

    try:
        assert _run(scenario()).status == "completed"
    finally:
        reset_env_config()
    assert kernel.registry_args[0]["include_shell_tools"] is expected
