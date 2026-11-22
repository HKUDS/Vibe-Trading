"""Recovery regressions for assistant replies interrupted by a restart."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.session.checkpoint import ResponseCheckpoint
from src.session.events import EventBus
from src.session.models import Attempt, AttemptStatus, Session
from src.session.service import SessionService
from src.session.store import SessionStore
from src.session.runtime import SessionRuntime


class _DummyIndex:
    def index_session(self, session_id: str, title: str) -> None:
        del session_id, title

    def index_message(self, session_id: str, role: str, content: str) -> None:
        del session_id, role, content


def _service(store: SessionStore, runs_dir: Path, monkeypatch) -> SessionService:
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    return SessionService(store=store, event_bus=EventBus(), runs_dir=runs_dir)


def test_stream_checkpoint_tracks_deltas_and_resets(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = Session(title="checkpoint")
    store.create_session(session)
    attempt = Attempt(session_id=session.session_id, prompt="hello")
    store.create_attempt(attempt)
    checkpoint = ResponseCheckpoint(store, attempt, min_interval_seconds=60)

    checkpoint.handle_event('item.delta', {"kind": 'text.delta', 'delta': 'first'})
    checkpoint.handle_event('item.delta', {"kind": 'text.delta', 'delta': ' second'})
    assert SessionRuntime(store.thread_log(session.session_id), session.session_id).partial_response(attempt.attempt_id) == "first"

    checkpoint.flush()
    assert (
        SessionRuntime(store.thread_log(session.session_id), session.session_id).partial_response(attempt.attempt_id)
        == "first second"
    )

    checkpoint.handle_event('item.delta', {"kind": 'text.reset', })
    assert SessionRuntime(store.thread_log(session.session_id), session.session_id).partial_response(attempt.attempt_id) == ""

    checkpoint.handle_event('item.delta', {"kind": 'text.delta', 'delta': 'replacement'})
    assert (
        SessionRuntime(store.thread_log(session.session_id), session.session_id).partial_response(attempt.attempt_id)
        == "replacement"
    )


def test_service_restart_recovers_partial_reply_once(
    tmp_path: Path, monkeypatch
) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = Session(title="restart")
    store.create_session(session)
    attempt = Attempt(session_id=session.session_id, prompt="analyze")
    attempt.mark_running()
    store.create_attempt(attempt)
    SessionRuntime(store.thread_log(session.session_id), session.session_id).record_checkpoint(attempt.attempt_id, "Partial answer")

    (store.thread_path(session.session_id).parent / "thread_migration.json").unlink()
    _service(store, tmp_path / "runs", monkeypatch)

    recovered = store.get_attempt(session.session_id, attempt.attempt_id)
    assert recovered is not None
    assert recovered.status == AttemptStatus.INTERRUPTED
    assert recovered.completed_at is not None
    replies = [
        message
        for message in store.get_messages(session.session_id)
        if message.linked_attempt_id == attempt.attempt_id
    ]
    assert len(replies) == 1
    assert "Partial answer" in replies[0].content
    assert replies[0].metadata == {
        "status": "interrupted",
        "partial": True,
        "recovery_reason": "service_restart",
    }
    assert not list(tmp_path.rglob("partial_response.json"))

    # Startup reconciliation must be safe to run repeatedly.
    _service(store, tmp_path / "runs", monkeypatch)
    replies = [
        message
        for message in store.get_messages(session.session_id)
        if message.linked_attempt_id == attempt.attempt_id
    ]
    assert len(replies) == 1


def test_service_restart_recovers_pending_attempt_without_partial(
    tmp_path: Path, monkeypatch
) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = Session(title="pending")
    store.create_session(session)
    attempt = Attempt(session_id=session.session_id, prompt="queued")
    store.create_attempt(attempt)

    _service(store, tmp_path / "runs", monkeypatch)

    recovered = store.get_attempt(session.session_id, attempt.attempt_id)
    assert recovered is not None
    assert recovered.status == AttemptStatus.INTERRUPTED
    reply = store.get_messages(session.session_id)[-1]
    assert "no complete assistant response was saved" in reply.content
    assert reply.metadata["partial"] is False


def test_restart_finishes_attempt_when_terminal_reply_was_already_appended(
    tmp_path: Path, monkeypatch
) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = Session(title="commit ordering")
    store.create_session(session)
    attempt = Attempt(session_id=session.session_id, prompt="answer")
    attempt.mark_running()
    store.create_attempt(attempt)
    runtime = SessionRuntime(store.thread_log(session.session_id), session.session_id)
    runtime.finish_turn(attempt.attempt_id, prompt=attempt.prompt, status="completed", summary="Complete answer")

    _service(store, tmp_path / "runs", monkeypatch)

    recovered = store.get_attempt(session.session_id, attempt.attempt_id)
    assert recovered is not None
    assert recovered.status == AttemptStatus.COMPLETED
    assert recovered.summary == "Complete answer"
    assert len([m for m in store.get_messages(session.session_id) if m.role == "assistant"]) == 1


def test_event_loop_shutdown_remains_recoverable(tmp_path: Path, monkeypatch) -> None:
    async def scenario() -> None:
        store = SessionStore(tmp_path / "sessions")
        service = _service(store, tmp_path / "runs", monkeypatch)
        session = service.create_session(title="shutdown")
        gate = asyncio.Event()

        async def wait_forever(attempt, messages=None, **kwargs):
            del attempt, messages, kwargs
            await gate.wait()
            return {"status": "success", "content": "too late"}

        monkeypatch.setattr(service._factory, "run", wait_forever)
        sent = await service.send_message(session.session_id, "keep this")
        await asyncio.sleep(0)
        task = service._active_tasks[session.session_id]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        attempt = store.get_attempt(session.session_id, sent["attempt_id"])
        assert attempt is not None
        assert attempt.status == AttemptStatus.RUNNING

        _service(store, tmp_path / "runs", monkeypatch)
        recovered = store.get_attempt(session.session_id, sent["attempt_id"])
        assert recovered is not None
        assert recovered.status == AttemptStatus.INTERRUPTED

    asyncio.run(scenario())
