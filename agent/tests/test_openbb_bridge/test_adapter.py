"""Unit tests for :class:`OpenBBQueryAdapter`."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("openbb_ai")

from src.openbb_bridge.adapter import OpenBBQueryAdapter


class _FakeEvent:
    def __init__(self, event_type, data):
        self.event_type = event_type
        self.data = data


class _FakeEventBus:
    def __init__(self, events):
        self._events = events
        self.cleared = []

    async def subscribe(self, session_id, last_event_id=None, *, replay_all=False):
        for event in self._events:
            yield event

    def clear(self, session_id):
        self.cleared.append(session_id)


class _FakeStore:
    def __init__(self):
        self.messages = []

    def append_message(self, message):
        self.messages.append(message)


class _FakeSessionService:
    def __init__(self, events):
        self.event_bus = _FakeEventBus(events)
        self.store = _FakeStore()
        self._sessions = {}
        self.sent = []
        self._counter = 0

    def create_session(self, title=""):
        self._counter += 1
        session_id = f"sess-{self._counter}"
        session = SimpleNamespace(session_id=session_id, title=title)
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id):
        return self._sessions.get(session_id)

    async def send_message(self, session_id, content, role="user"):
        self.sent.append((session_id, content, role))
        return {"message_id": "m1", "attempt_id": "att1"}


def _human(text):
    return SimpleNamespace(role="human", content=text)


def _ai(text):
    return SimpleNamespace(role="ai", content=text)


def _request(messages):
    return SimpleNamespace(
        messages=messages, widgets=None, workspace_state=None, context=None
    )


async def _collect(agen):
    return [item async for item in agen]


def test_happy_path_streams_text_and_completes():
    events = [
        _FakeEvent("attempt.started", {"attempt_id": "att1"}),
        _FakeEvent("text_delta", {"delta": "Hello ", "attempt_id": "att1"}),
        _FakeEvent("text_delta", {"delta": "world", "attempt_id": "att1"}),
        _FakeEvent("attempt.completed", {"attempt_id": "att1", "summary": "done"}),
    ]
    service = _FakeSessionService(events)
    adapter = OpenBBQueryAdapter(session_service=service)

    out = asyncio.run(_collect(adapter.handle_query(_request([_human("hi")]))))

    # The user message was dispatched to a new session.
    assert len(service.sent) == 1
    assert service.sent[0][2] == "user"
    # At least the two text chunks were emitted.
    assert len(out) >= 2


def test_no_execution_when_last_message_not_human():
    service = _FakeSessionService([])
    adapter = OpenBBQueryAdapter(session_service=service)

    out = asyncio.run(
        _collect(adapter.handle_query(_request([_human("hi"), _ai("answer")])))
    )

    assert service.sent == []  # nothing dispatched
    assert len(out) == 1  # only the "waiting for input" reasoning step


def test_identical_openings_never_share_a_session():
    """Two conversations that start the same way must stay isolated.

    The original implementation keyed a persistent session on a hash of the
    first message, so any two chats opening with "hello" merged and leaked each
    other's history. QueryRequest carries no conversation id, so each request
    now gets its own ephemeral session instead.
    """
    events = [_FakeEvent("attempt.completed", {"attempt_id": "att1", "summary": ""})]
    service = _FakeSessionService(events)
    adapter = OpenBBQueryAdapter(session_service=service)

    asyncio.run(_collect(adapter.handle_query(_request([_human("hello")]))))
    asyncio.run(_collect(adapter.handle_query(_request([_human("hello")]))))

    sessions = [sent[0] for sent in service.sent]
    assert len(sessions) == 2
    assert len(set(sessions)) == 2
    # No cross-request mapping state is retained at all.
    assert not hasattr(adapter, "_session_map")


def test_full_supplied_history_is_replayed_on_every_request():
    """OpenBB is stateless: later turns must still replay the whole history."""
    events = [_FakeEvent("attempt.completed", {"attempt_id": "att1", "summary": ""})]
    service = _FakeSessionService(events)
    adapter = OpenBBQueryAdapter(session_service=service)

    history = [
        _human("first question"),
        _ai("first answer"),
        _human("second question"),
        _ai("second answer"),
        _human("third question"),
    ]
    asyncio.run(_collect(adapter.handle_query(_request(history))))

    replayed = [(m.role, m.content) for m in service.store.messages]
    assert replayed == [
        ("user", "first question"),
        ("assistant", "first answer"),
        ("user", "second question"),
        ("assistant", "second answer"),
    ]
    # Only the final human turn goes through send_message, so exactly one
    # attempt is started.
    assert len(service.sent) == 1
    assert service.sent[0][1].endswith("third question")


def test_tool_messages_are_not_replayed_as_turns():
    events = [_FakeEvent("attempt.completed", {"attempt_id": "att1", "summary": ""})]
    service = _FakeSessionService(events)
    adapter = OpenBBQueryAdapter(session_service=service)

    messages = [
        _human("q1"),
        SimpleNamespace(role="tool", function="get_price", data=[]),
        _human("q2"),
    ]
    asyncio.run(_collect(adapter.handle_query(_request(messages))))

    assert [m.role for m in service.store.messages] == ["user"]


def test_event_buffer_is_released_after_the_stream_ends():
    events = [_FakeEvent("attempt.completed", {"attempt_id": "att1", "summary": ""})]
    service = _FakeSessionService(events)
    adapter = OpenBBQueryAdapter(session_service=service)

    asyncio.run(_collect(adapter.handle_query(_request([_human("hi")]))))

    assert service.event_bus.cleared == [service.sent[0][0]]


def test_failed_attempt_emits_error_and_message():
    events = [
        _FakeEvent("attempt.started", {"attempt_id": "att1"}),
        _FakeEvent("attempt.failed", {"attempt_id": "att1", "error": "kaboom"}),
    ]
    service = _FakeSessionService(events)
    adapter = OpenBBQueryAdapter(session_service=service)

    out = asyncio.run(_collect(adapter.handle_query(_request([_human("hi")]))))
    # An error reasoning step + a fallback message chunk should be present.
    assert len(out) >= 2


def test_events_from_other_attempts_are_ignored():
    events = [
        _FakeEvent("text_delta", {"delta": "stale", "attempt_id": "OTHER"}),
        _FakeEvent("text_delta", {"delta": "fresh", "attempt_id": "att1"}),
        _FakeEvent("attempt.completed", {"attempt_id": "att1", "summary": ""}),
    ]
    service = _FakeSessionService(events)
    adapter = OpenBBQueryAdapter(session_service=service)

    out = asyncio.run(_collect(adapter.handle_query(_request([_human("hi")]))))
    # Only the fresh chunk should have been emitted (stale one filtered out).
    assert len(out) == 1
