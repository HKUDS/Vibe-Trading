"""Shipping rename routes must keep search's conversation labels current."""

import asyncio
import json
import sys
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from src.api.sessions_routes import UpdateSessionRequest, register_sessions_routes
from src.session.events import EventBus
from src.session.search import SessionSearchIndex
from src.session.service import SessionService
from src.session.store import SessionStore
from src.tools.session_search_tool import SessionSearchTool


@pytest.fixture
def owned_title_routes(tmp_path, monkeypatch):
    index = SessionSearchIndex(tmp_path / "search.db")
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: index)
    monkeypatch.setattr("src.session.search.get_shared_index", lambda: index)
    service = SessionService(
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(),
        runs_dir=tmp_path / "runs",
    )
    original = "volatility synthetic prompt"
    session = service.create_session(title=original)
    sibling = service.create_session(title="Unrelated conversation")
    # The auto-title route reads a real user message, admitted directly to the
    # store/index to avoid invoking an agent or provider during fixture setup.
    from src.session.models import Message

    service.store.append_message(
        Message(session_id=session.session_id, role="user", content=original)
    )
    index.index_message(session.session_id, "user", original)
    before = index.search("volatility")[0]
    host = SimpleNamespace(
        require_auth=lambda: None,
        require_event_stream_auth=lambda: None,
        _get_session_service=lambda: service,
        _validate_path_param=lambda value, kind: None,
    )
    # This is the route module's documented host-composition boundary. Actual
    # route, persistence, index and search tool implementations remain intact.
    monkeypatch.setitem(sys.modules, "api_server", host)
    app = FastAPI()
    register_sessions_routes(app)
    try:
        yield service, index, app, session, sibling, before
    finally:
        index.close()


@pytest.mark.parametrize("automatic", [False, True])
def test_registered_title_route_updates_actual_search(
    owned_title_routes, monkeypatch, automatic
):
    service, index, app, session, sibling, before = owned_title_routes
    title = "Renamed synthetic analysis"
    if automatic:
        from src.providers import chat

        class OwnedTitleProvider:
            def chat(self, messages, timeout):
                return SimpleNamespace(content=title)

            def close(self):
                pass

        monkeypatch.setattr(chat, "ChatLLM", OwnedTitleProvider)
        route = next(
            r for r in app.routes if r.path == "/sessions/{session_id}/title/auto"
        )
        result = asyncio.run(route.endpoint(session.session_id))
    else:
        route = next(
            r
            for r in app.routes
            if r.path == "/sessions/{session_id}" and "PATCH" in r.methods
        )
        result = asyncio.run(
            route.endpoint(session.session_id, UpdateSessionRequest(title=title))
        )
    assert result["status"] == "updated"
    assert service.store.get_session(session.session_id).title == title
    reply = json.loads(SessionSearchTool().execute(query="volatility"))
    assert reply["status"] == "ok"
    match = reply["results"][0]
    assert match["title"] == title
    assert match["session_id"] == session.session_id
    assert match["message_count"] == before.message_count == 1
    assert match["started_at"] == before.started_at
    assert (
        service.store.get_session(sibling.session_id).title == "Unrelated conversation"
    )
    assert (
        index._get_conn()
        .execute("SELECT title FROM sessions WHERE id = ?", (sibling.session_id,))
        .fetchone()[0]
        == "Unrelated conversation"
    )


@pytest.mark.parametrize("manual_rename", [False, True])
def test_auto_title_wait_preserves_live_session_updates(
    owned_title_routes, monkeypatch, manual_rename
):
    service, index, app, session, sibling, before = owned_title_routes
    from src.providers import chat

    provider_started, provider_release = threading.Event(), threading.Event()
    provider_closed = threading.Event()

    class OwnedTitleProvider:
        def chat(self, messages, timeout):
            provider_started.set()
            assert provider_release.wait(3)
            return SimpleNamespace(content="Generated synthetic title")

        def close(self):
            provider_closed.set()

    monkeypatch.setattr(chat, "ChatLLM", OwnedTitleProvider)
    auto = next(
        r.endpoint for r in app.routes if r.path == "/sessions/{session_id}/title/auto"
    )
    patch = next(
        r.endpoint
        for r in app.routes
        if r.path == "/sessions/{session_id}" and "PATCH" in r.methods
    )

    async def hold_agent_execution(*args, **kwargs):
        # Real send_message admission persists its attempt/config/message.
        # Only external agent execution is held so no model/tool is invoked.
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "_run_attempt", hold_agent_execution)

    async def scenario():
        generation = asyncio.create_task(auto(session.session_id))
        try:
            assert await asyncio.to_thread(provider_started.wait, 2)
            admission = await service.send_message(
                session.session_id,
                "volatility accepted while naming",
                include_shell_tools=True,
            )
            if manual_rename:
                await patch(
                    session.session_id,
                    UpdateSessionRequest(title="Manual protected title"),
                )
        finally:
            provider_release.set()
        result = await generation
        current = service.store.get_session(session.session_id)
        expected = (
            "Manual protected title" if manual_rename else "Generated synthetic title"
        )
        assert current.last_attempt_id == admission["attempt_id"]
        assert current.config["include_shell_tools"] is True
        assert current.title == expected
        assert result["status"] == ("kept" if manual_rename else "updated")
        assert provider_closed.is_set()
        assert len(service.get_messages(session.session_id)) == 1
        match = json.loads(SessionSearchTool().execute(query="volatility"))["results"][
            0
        ]
        assert match["title"] == expected
        assert match["message_count"] == 1
        assert match["started_at"] == before.started_at
        assert (
            service.store.get_session(sibling.session_id).title
            == "Unrelated conversation"
        )
        for task in service._active_tasks.values():
            task.cancel()
        await asyncio.gather(*service._active_tasks.values(), return_exceptions=True)

    asyncio.run(scenario())
