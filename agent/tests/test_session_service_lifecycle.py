"""Session lifecycle regression tests: concurrency guard, cancellation, metrics persistence.

Covers session/service.py fixes #1-#4:

* #1: ``send_message`` rejects concurrent sends with ``SessionBusyError`` so a
  second AgentLoop cannot run against the same session.
* #2: ``_run_with_agent`` refuses to overwrite an existing ``_active_loops``
  entry instead of silently bumping it (which would make ``cancel_current``
  cancel the wrong loop).
* #3: A cancelled AgentLoop result maps to ``AttemptStatus.CANCELLED`` via
  ``Attempt.mark_cancelled``; the previous code lumped the result into
  ``mark_failed``.
* #4: ``_run_attempt`` mirrors ``attempt.run_dir`` with ``attempt.metrics`` so
  backtest metrics survive into the persisted attempt and reply metadata.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.session.events import EventBus
from src.session.models import Attempt, AttemptStatus
from src.session.service import SessionBusyError, SessionService
from src.session.store import SessionStore


class _StubAgentLoop:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def run(self, **kwargs: Any) -> dict:
        return {"status": "success"}


class _DummyIndex:
    def index_session(self, session_id: str, title: str) -> None:
        del session_id, title

    def index_message(self, session_id: str, role: str, content: str) -> None:
        del session_id, role, content


def _service(tmp_path: Path) -> SessionService:
    return SessionService(
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(),
        runs_dir=tmp_path / "runs",
    )


def _stub_build_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the heavy dependencies of ``_run_attempt`` / ``_run_with_agent``."""
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    monkeypatch.setattr("src.providers.chat.ChatLLM", lambda: object())
    monkeypatch.setattr("src.memory.persistent.PersistentMemory", lambda: object())
    monkeypatch.setattr("src.agent.loop.AgentLoop", _StubAgentLoop)
    monkeypatch.setattr(
        "src.config.loader.load_runtime_agent_config",
        lambda overrides=None: object(),
    )
    monkeypatch.setattr(
        "src.config.loader.sanitize_session_overrides",
        lambda overrides: dict(overrides) if overrides else {},
    )
    monkeypatch.setattr(
        "src.tools.build_registry",
        lambda **kw: object(),
    )


def test_send_message_rejects_concurrent_runs_with_session_busy_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Issue #1: a second send while the first AgentLoop is in-flight rejects."""
    _stub_build_env(monkeypatch)
    service = _service(tmp_path)
    session = service.create_session(title="busy")

    # Plant an active loop to simulate an in-flight AgentLoop.
    service._active_loops[session.session_id] = _StubAgentLoop()

    async def _exercise() -> None:
        with pytest.raises(SessionBusyError):
            await service.send_message(session.session_id, "second message")

    asyncio.run(_exercise())


def test_send_message_after_loop_teardown_starts_a_new_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Once ``_active_loops`` is cleared, the gate opens for the next send."""
    _stub_build_env(monkeypatch)
    service = _service(tmp_path)
    session = service.create_session(title="queue")

    service._active_loops[session.session_id] = _StubAgentLoop()

    async def _exercise() -> dict:
        with pytest.raises(SessionBusyError):
            await service.send_message(session.session_id, "first")

        service._active_loops.pop(session.session_id, None)
        return await service.send_message(session.session_id, "second")

    result = asyncio.run(_exercise())
    assert result["attempt_id"]
    assert result["message_id"]


def test_run_attempt_refuses_to_overwrite_active_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Issue #2: ``_active_loops`` is never silently overwritten.

    Belt-and-braces in case a future caller bypasses ``send_message``.
    """
    _stub_build_env(monkeypatch)

    service = _service(tmp_path)
    session = service.create_session(title="race")
    attempt = Attempt(session_id=session.session_id, prompt="go")

    existing = _StubAgentLoop()
    service._active_loops[session.session_id] = existing

    async def _exercise() -> None:
        with pytest.raises(SessionBusyError):
            await service._run_with_agent(attempt, messages=[], session_config={})

    asyncio.run(_exercise())


def test_run_attempt_marks_cancelled_status_via_mark_cancelled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Issue #3: a cancelled AgentLoop result becomes ``AttemptStatus.CANCELLED``."""
    _stub_build_env(monkeypatch)
    service = _service(tmp_path)
    session = service.create_session(title="cancel")
    attempt = Attempt(session_id=session.session_id, prompt="go")

    async def _fake_run_with_agent(
        self_attempt: Attempt,
        **_: Any,
    ) -> dict:
        return {
            "status": "cancelled",
            "reason": "cancelled by user",
            "run_dir": None,
            "content": "",
        }

    monkeypatch.setattr(service, "_run_with_agent", _fake_run_with_agent)
    monkeypatch.setattr(service.event_bus, "emit", lambda *args, **kwargs: None)

    asyncio.run(service._run_attempt(session, attempt))

    assert attempt.status == AttemptStatus.CANCELLED
    assert attempt.error == "cancelled by user"


def test_run_attempt_assigns_metrics_to_attempt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Issue #4: ``_run_attempt`` mirrors ``attempt.run_dir`` with ``attempt.metrics``."""
    _stub_build_env(monkeypatch)
    service = _service(tmp_path)
    session = service.create_session(title="metrics")
    attempt = Attempt(session_id=session.session_id, prompt="go")

    async def _fake_run_with_agent(
        self_attempt: Attempt,
        **_: Any,
    ) -> dict:
        return {
            "status": "success",
            "content": "ok",
            "run_dir": str(tmp_path / "run-abc"),
            "metrics": {"sharpe": 1.23, "max_drawdown": -0.08},
        }

    monkeypatch.setattr(service, "_run_with_agent", _fake_run_with_agent)
    monkeypatch.setattr(service.event_bus, "emit", lambda *args, **kwargs: None)

    asyncio.run(service._run_attempt(session, attempt))

    assert attempt.run_dir == str(tmp_path / "run-abc")
    assert attempt.metrics == {"sharpe": 1.23, "max_drawdown": -0.08}
    assert attempt.status == AttemptStatus.COMPLETED


def test_attempt_mark_cancelled_sets_status_and_error() -> None:
    """``Attempt.mark_cancelled`` is distinct from ``mark_failed``."""
    attempt = Attempt(prompt="go")
    attempt.mark_running()
    attempt.mark_cancelled(reason="cancelled by user")

    assert attempt.status == AttemptStatus.CANCELLED
    assert attempt.error == "cancelled by user"
    assert attempt.completed_at is not None

    # CANCELLED and FAILED are distinct enums so the UI can branch.
    assert AttemptStatus.CANCELLED.value != AttemptStatus.FAILED.value


# ---------------------------------------------------------------------------
# LOW-severity fixes (Vibe-Trading review)
# ---------------------------------------------------------------------------


def test_run_attempt_uses_diagnostic_placeholder_for_empty_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """LOW Issue #2: when AgentLoop reports success with empty content, the
    attempt summary must surface a diagnostic placeholder so the UI does not
    silently claim ``Strategy execution completed.`` later."""
    service = _service(tmp_path)
    session = service.create_session(title="empty-success")
    attempt = Attempt(session_id=session.session_id, prompt="go")

    async def _fake_run_with_agent(*_: Any, **__: Any) -> dict:
        return {
            "status": "success",
            "content": "",
            "run_dir": None,
            "metrics": None,
        }

    monkeypatch.setattr(service, "_run_with_agent", _fake_run_with_agent)
    monkeypatch.setattr(service.event_bus, "emit", lambda *args, **kwargs: None)

    asyncio.run(service._run_attempt(session, attempt))

    assert attempt.status == AttemptStatus.COMPLETED
    assert attempt.summary == "(LLM returned empty completion)"


def test_convert_messages_to_history_keeps_fallback_when_message_exceeds_budget() -> None:
    """LOW Issue #3: when a single prior message exceeds the 12KB budget,
    the trimmed history must still contain at least a truncated version of
    that message instead of being empty."""
    # Build a single 15KB message that lands BEFORE the current turn so it
    # is actually fed into the trim loop. The current-turn message is
    # excluded by ``messages[:-1]`` in _convert_messages_to_history.
    big_prior = "x" * 15_000
    messages = [
        _FakeMessage("system", "you are a helpful assistant"),
        _FakeMessage("user", big_prior),
        _FakeMessage("assistant", "earlier answer"),
        _FakeMessage("user", "current turn prompt"),
    ]

    trimmed = SessionService._convert_messages_to_history(messages)

    assert trimmed, "history must not be empty when prior messages exist"
    # The big prior user message must survive in truncated form (per-message
    # cap = 6000 chars).
    assert any(
        "x" * 100 in m["content"] for m in trimmed
    ), "big prior user message tail must survive the budget trim"


def test_convert_messages_to_history_truncates_oversized_message_in_place() -> None:
    """LOW Issue #3: oversized messages must be truncated to PER_MESSAGE_CAP
    rather than dropped wholesale from the budget loop."""
    big_prior = "x" * 15_000
    messages = [
        _FakeMessage("system", "you are a helpful assistant"),
        _FakeMessage("user", big_prior),
        _FakeMessage("assistant", "ok"),
        _FakeMessage("user", "current turn"),
    ]

    trimmed = SessionService._convert_messages_to_history(messages)

    assert trimmed, "history must not be empty"
    # The truncated user message must be at most the per-message cap, not
    # the full 15KB.
    user_msgs = [m for m in trimmed if m["role"] == "user"]
    assert any(len(m["content"]) <= 6_000 + 100 for m in user_msgs), (
        "oversized prior message must be truncated to the per-message cap"
    )


class _FakeMessage:
    """Minimal duck-typed Message for ``_convert_messages_to_history``."""

    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content
