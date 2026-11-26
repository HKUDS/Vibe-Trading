"""Historical prompt edits truncate chat only and regenerate from the retained prefix."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from src.api.sessions_routes import EditMessageRequest, register_sessions_routes
from src.session.events import EventBus
from src.session.models import Message
from src.session.search import SessionSearchIndex
from src.session.service import SessionBusyError, SessionService
from src.session.store import SessionStore


@pytest.fixture
def edit_service(tmp_path, monkeypatch):
    index = SessionSearchIndex(tmp_path / "search.db")
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: index)
    service = SessionService(
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(),
        runs_dir=tmp_path / "runs",
    )

    async def fake_agent(attempt, messages=None, **kwargs):
        del messages, kwargs
        return {"status": "success", "content": f"answer: {attempt.prompt}"}

    monkeypatch.setattr(service, "_run_with_agent", fake_agent)
    try:
        yield service, index
    finally:
        index.close()


async def _wait_until_idle(service: SessionService, session_id: str) -> None:
    for _ in range(100):
        if session_id not in service._inflight:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("session did not become idle")


def test_edit_middle_prompt_truncates_chat_and_keeps_prior_attempt_as_parent(
    edit_service,
):
    service, index = edit_service

    async def scenario():
        session = service.create_session(title="edit history")
        first = await service.send_message(session.session_id, "first prompt")
        await _wait_until_idle(service, session.session_id)
        await service.send_message(session.session_id, "second prompt")
        await _wait_until_idle(service, session.session_id)
        await service.send_message(session.session_id, "removedzebraword")
        await _wait_until_idle(service, session.session_id)

        target = next(
            message
            for message in service.get_messages(session.session_id)
            if message.role == "user" and message.content == "second prompt"
        )
        edited = await service.edit_message_and_regenerate(
            session.session_id,
            target.message_id,
            "edited second prompt",
        )
        await _wait_until_idle(service, session.session_id)

        messages = service.get_messages(session.session_id)
        assert [(message.role, message.content) for message in messages] == [
            ("user", "first prompt"),
            ("assistant", "answer: first prompt"),
            ("user", "edited second prompt"),
            ("assistant", "answer: edited second prompt"),
        ]
        stored = service.store.get_session(session.session_id)
        attempt = service.store.get_attempt(session.session_id, edited["attempt_id"])
        assert stored.last_attempt_id == edited["attempt_id"]
        assert attempt.parent_attempt_id == first["attempt_id"]
        assert len(service.store.list_attempts()) == 4
        assert index.search("edited second prompt")[0].session_id == session.session_id
        assert index.search("removedzebraword") == []

    asyncio.run(scenario())


def test_edit_is_refused_while_session_is_busy_without_mutating_history(
    edit_service,
    monkeypatch,
):
    service, _index = edit_service
    gate = asyncio.Event()

    async def waiting_agent(attempt, messages=None, **kwargs):
        del attempt, messages, kwargs
        await gate.wait()
        return {"status": "success", "content": "done"}

    monkeypatch.setattr(service, "_run_with_agent", waiting_agent)

    async def scenario():
        session = service.create_session(title="busy edit")
        await service.send_message(session.session_id, "keep this")
        target = service.get_messages(session.session_id)[0]
        before = service.store._messages_file(session.session_id).read_bytes()

        with pytest.raises(SessionBusyError):
            await service.edit_message_and_regenerate(
                session.session_id,
                target.message_id,
                "must not persist",
            )

        assert service.store._messages_file(session.session_id).read_bytes() == before
        gate.set()
        await _wait_until_idle(service, session.session_id)

    asyncio.run(scenario())


def test_edit_rejects_non_user_and_missing_messages(edit_service):
    service, _index = edit_service

    async def scenario():
        session = service.create_session(title="invalid edit")
        assistant = Message(session_id=session.session_id, role="assistant", content="answer")
        service.store.append_message(assistant)

        with pytest.raises(ValueError, match="Only user messages"):
            await service.edit_message_and_regenerate(
                session.session_id,
                assistant.message_id,
                "edited",
            )
        with pytest.raises(LookupError, match="not found"):
            await service.edit_message_and_regenerate(
                session.session_id,
                "missing",
                "edited",
            )

        assert [message.content for message in service.get_messages(session.session_id)] == ["answer"]

    asyncio.run(scenario())


def test_search_index_failure_restores_exact_original_transcript(edit_service, monkeypatch):
    service, index = edit_service

    async def scenario():
        session = service.create_session(title="index rollback")
        await service.send_message(session.session_id, "first prompt")
        await _wait_until_idle(service, session.session_id)
        await service.send_message(session.session_id, "second prompt")
        await _wait_until_idle(service, session.session_id)
        await service.send_message(session.session_id, "keep suffix")
        await _wait_until_idle(service, session.session_id)
        target = next(
            message
            for message in service.get_messages(session.session_id)
            if message.role == "user" and message.content == "second prompt"
        )
        before = [(message.role, message.content) for message in service.get_messages(session.session_id)]

        def fail_index(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("index unavailable")

        monkeypatch.setattr(index, "replace_session_messages", fail_index)
        with pytest.raises(RuntimeError, match="index unavailable"):
            await service.edit_message_and_regenerate(
                session.session_id,
                target.message_id,
                "editeduniquetoken",
            )

        assert [(message.role, message.content) for message in service.get_messages(session.session_id)] == before
        assert session.session_id not in service._inflight

    asyncio.run(scenario())


@pytest.mark.parametrize("failure_stage", ["create_attempt", "update_session", "create_task"])
def test_preflight_failure_restores_chat_search_and_session(
    edit_service,
    monkeypatch,
    failure_stage,
):
    service, index = edit_service

    async def scenario():
        session = service.create_session(title="scheduling rollback")
        await service.send_message(session.session_id, "first prompt")
        await _wait_until_idle(service, session.session_id)
        await service.send_message(session.session_id, "second prompt")
        await _wait_until_idle(service, session.session_id)
        await service.send_message(session.session_id, "keep suffix")
        await _wait_until_idle(service, session.session_id)
        target = next(
            message
            for message in service.get_messages(session.session_id)
            if message.role == "user" and message.content == "second prompt"
        )
        before_messages = [(message.role, message.content) for message in service.get_messages(session.session_id)]
        before_session = service.store.get_session(session.session_id).to_dict()
        before_attempts = {attempt.attempt_id for attempt in service.store.list_attempts()}
        emitted_events: list[str] = []
        service.event_bus.add_listener(lambda event: emitted_events.append(event.event_type))

        if failure_stage == "create_attempt":

            def fail(*args, **kwargs):
                del args, kwargs
                raise RuntimeError("attempt storage unavailable")

            monkeypatch.setattr(service.store, "create_attempt", fail)
        elif failure_stage == "update_session":
            original_update = service.store.update_session
            calls = 0

            def fail_once(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("session storage unavailable")
                return original_update(*args, **kwargs)

            monkeypatch.setattr(service.store, "update_session", fail_once)
        else:

            def fail(coroutine, *args, **kwargs):
                del args, kwargs
                coroutine.close()
                raise RuntimeError("task scheduling unavailable")

            monkeypatch.setattr("src.session.service.asyncio.create_task", fail)

        with pytest.raises(RuntimeError, match="unavailable"):
            await service.edit_message_and_regenerate(
                session.session_id,
                target.message_id,
                "editeduniquetoken",
            )

        assert [
            (message.role, message.content) for message in service.get_messages(session.session_id)
        ] == before_messages
        assert service.store.get_session(session.session_id).to_dict() == before_session
        assert {attempt.attempt_id for attempt in service.store.list_attempts()} == before_attempts
        assert index.search("keep suffix")[0].session_id == session.session_id
        assert index.search("editeduniquetoken") == []
        assert "message.edited" not in emitted_events
        assert "attempt.created" not in emitted_events
        assert session.session_id not in service._inflight

    asyncio.run(scenario())


def test_failed_regeneration_keeps_edit_and_retry_does_not_duplicate_prompt(
    edit_service,
    monkeypatch,
):
    service, _index = edit_service
    fail_regeneration = True

    async def flaky_agent(attempt, messages=None, **kwargs):
        del messages, kwargs
        nonlocal fail_regeneration
        if attempt.prompt == "edited prompt" and fail_regeneration:
            fail_regeneration = False
            return {
                "status": "error",
                "reason": "regeneration failed",
                "run_dir": "/tmp/run-failed-edit",
            }
        return {"status": "success", "content": f"answer: {attempt.prompt}"}

    monkeypatch.setattr(service, "_run_with_agent", flaky_agent)

    async def scenario():
        session = service.create_session(title="retry edit")
        await service.send_message(session.session_id, "original prompt")
        await _wait_until_idle(service, session.session_id)
        target = service.get_messages(session.session_id)[0]

        failed = await service.edit_message_and_regenerate(
            session.session_id,
            target.message_id,
            "edited prompt",
        )
        await _wait_until_idle(service, session.session_id)

        failed_messages = service.get_messages(session.session_id)
        assert [(message.role, message.content) for message in failed_messages] == [
            ("user", "edited prompt"),
            ("assistant", "Execution failed: regeneration failed"),
        ]
        assert failed_messages[-1].metadata["status"] == "failed"
        assert failed_messages[-1].metadata["edited_message_id"] == target.message_id
        assert failed_messages[-1].metadata["run_id"] == "run-failed-edit"
        assert service.store.get_attempt(session.session_id, failed["attempt_id"]).status.value == "failed"
        reloaded = SessionStore(service.store.base_dir)
        assert reloaded.get_messages(session.session_id)[0].content == "edited prompt"

        retried = await service.edit_message_and_regenerate(
            session.session_id,
            target.message_id,
            "edited prompt",
        )
        await _wait_until_idle(service, session.session_id)

        messages = service.get_messages(session.session_id)
        assert [(message.role, message.content) for message in messages] == [
            ("user", "edited prompt"),
            ("assistant", "answer: edited prompt"),
        ]
        assert retried["attempt_id"] != failed["attempt_id"]
        assert len(service.store.list_attempts()) == 3
        assert reloaded.get_messages(session.session_id) == messages

    asyncio.run(scenario())


def test_exceptional_regeneration_persists_retryable_edit_failure(edit_service, monkeypatch):
    service, index = edit_service

    async def raising_agent(attempt, messages=None, **kwargs):
        del attempt, messages, kwargs
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(service, "_run_with_agent", raising_agent)

    async def scenario():
        session = service.create_session(title="exceptional edit")
        await service.send_message(session.session_id, "original prompt")
        await _wait_until_idle(service, session.session_id)
        target = service.get_messages(session.session_id)[0]

        edited = await service.edit_message_and_regenerate(
            session.session_id,
            target.message_id,
            "edited prompt",
        )
        await _wait_until_idle(service, session.session_id)

        messages = service.get_messages(session.session_id)
        assert [(message.role, message.content) for message in messages] == [
            ("user", "edited prompt"),
            ("assistant", "Execution failed: provider unavailable"),
        ]
        assert messages[-1].linked_attempt_id == edited["attempt_id"]
        assert messages[-1].metadata == {
            "status": "failed",
            "edited_message_id": target.message_id,
        }
        assert service.store.get_attempt(session.session_id, edited["attempt_id"]).status.value == "failed"
        assert index.search("provider unavailable")[0].session_id == session.session_id
        assert SessionStore(service.store.base_dir).get_messages(session.session_id) == messages

    asyncio.run(scenario())


def test_edit_keeps_old_target_in_bounded_regeneration_context(edit_service, monkeypatch):
    service, _index = edit_service
    seen_history = []

    async def recording_agent(attempt, messages=None, **kwargs):
        del attempt, kwargs
        seen_history.extend(messages)
        return {"status": "success", "content": "done"}

    monkeypatch.setattr(service, "_run_with_agent", recording_agent)

    async def scenario():
        session = service.create_session(title="old prompt")
        for index in range(120):
            service.store.append_message(
                Message(
                    session_id=session.session_id,
                    role="user",
                    content=f"prior {index}",
                )
            )
        target = Message(session_id=session.session_id, role="user", content="old target")
        service.store.append_message(target)
        service.store.append_message(
            Message(
                session_id=session.session_id,
                role="assistant",
                content="removed suffix",
            )
        )

        await service.edit_message_and_regenerate(
            session.session_id,
            target.message_id,
            "edited old target",
        )
        await _wait_until_idle(service, session.session_id)

        assert len(seen_history) == 100
        assert seen_history[0].content == "prior 21"
        assert seen_history[-1].message_id == target.message_id
        assert seen_history[-1].content == "edited old target"

    asyncio.run(scenario())


def test_message_list_can_return_full_history_for_editing(edit_service, monkeypatch):
    service, _index = edit_service
    host = SimpleNamespace(
        require_auth=lambda: None,
        require_event_stream_auth=lambda: None,
        _get_session_service=lambda: service,
        _validate_path_param=lambda value, kind: None,
        _shell_tools_enabled_for_request=lambda request: False,
    )
    monkeypatch.setitem(sys.modules, "api_server", host)
    app = FastAPI()
    register_sessions_routes(app)
    endpoint = next(
        route.endpoint
        for route in app.routes
        if route.path == "/sessions/{session_id}/messages" and "GET" in route.methods
    )
    session = service.create_session(title="full history")
    for index in range(101):
        service.store.append_message(
            Message(
                session_id=session.session_id,
                role="user",
                content=f"prompt {index}",
            )
        )

    limited = asyncio.run(endpoint(session.session_id, 100, False))
    complete = asyncio.run(endpoint(session.session_id, 100, True))

    assert len(limited) == 100
    assert limited[0].content == "prompt 1"
    assert len(complete) == 101
    assert complete[0].content == "prompt 0"


def test_edit_route_returns_attempt_and_uses_full_prompt_content(
    edit_service,
    monkeypatch,
):
    service, _index = edit_service
    host = SimpleNamespace(
        require_auth=lambda: None,
        require_event_stream_auth=lambda: None,
        _get_session_service=lambda: service,
        _validate_path_param=lambda value, kind: None,
        _shell_tools_enabled_for_request=lambda request: False,
    )
    monkeypatch.setitem(sys.modules, "api_server", host)
    app = FastAPI()
    register_sessions_routes(app)
    endpoint = next(
        route.endpoint for route in app.routes if route.path == "/sessions/{session_id}/messages/{message_id}"
    )

    async def scenario():
        session = service.create_session(title="route edit")
        await service.send_message(session.session_id, "before")
        await _wait_until_idle(service, session.session_id)
        target = service.get_messages(session.session_id)[0]
        raw_prompt = '[Uploaded files: [{"filename":"data.csv","path":"/tmp/data.csv"}]]\n\nafter'

        result = await endpoint(
            session.session_id,
            target.message_id,
            EditMessageRequest(content=raw_prompt),
            SimpleNamespace(),
        )
        await _wait_until_idle(service, session.session_id)

        assert result["message_id"] == target.message_id
        assert result["attempt_id"]
        assert service.get_messages(session.session_id)[0].content == raw_prompt

    asyncio.run(scenario())
