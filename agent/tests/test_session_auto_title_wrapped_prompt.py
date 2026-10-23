"""Auto-titling must see through the wrappers the web composer prepends.

``frontend/src/pages/Agent.tsx`` creates the session with the *raw* prompt
(``prompt.trim().slice(0, 50)`` at :1428 and :1515) but POSTs a wrapped first
message: ``buildChatPrompt`` adds ``SWARM_PROMPT_PREFIX`` and/or the
``[Uploaded files: ...]`` envelope, and goal mode sends
``GOAL_KICKOFF_PREFIX + objective``. ``toDisplayPrompt`` (Agent.tsx:139-171)
strips exactly those wrappers for rendering, so the route's manual-rename
check has to strip them too -- otherwise every swarm / attachment / goal
session is misread as a manual rename and keeps its raw truncated prompt
forever (CONTRIBUTING.md:36-37).
"""

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from src.api.sessions_routes import UpdateSessionRequest, register_sessions_routes
from src.session.events import EventBus
from src.session.search import SessionSearchIndex
from src.session.service import SessionService
from src.session.store import SessionStore

GENERATED_TITLE = "Portfolio volatility review"
RAW_PROMPT = "analyse portfolio volatility"

# Mirrors frontend/src/lib/chatPrompt.ts:6-7.
SWARM_PROMPT_PREFIX = (
    "[Swarm Team Mode] Use the swarm tool to assemble the best specialist team "
    "for this task. Auto-select the most appropriate preset.\n\n"
)
# Mirrors frontend/src/pages/Agent.tsx:126-131.
GOAL_KICKOFF_PREFIX = "\n".join(
    [
        "Start working on this research goal now.",
        "Keep it research-only, use available tools when evidence is needed, "
        "add concrete evidence to the goal ledger, and keep going until the "
        "goal is complete, blocked, waiting for user input, or budget-limited.",
        "",
        "Goal: ",
    ]
)


def _attachment_envelope(prompt: str) -> str:
    """Mirrors prependUploadedAttachments (frontend/src/lib/attachments.ts:11-21)."""
    payload = json.dumps(
        [{"filename": "positions.csv", "path": "/tmp/uploads/positions.csv"}],
        separators=(",", ":"),
    )
    return f"[Uploaded files: {payload}]\n\n{prompt}"


WRAPPERS = {
    "swarm": lambda prompt: f"{SWARM_PROMPT_PREFIX}{prompt}",
    "attachments": _attachment_envelope,
    "goal_kickoff": lambda prompt: f"{GOAL_KICKOFF_PREFIX}{prompt}",
    "swarm_with_attachments": lambda prompt: _attachment_envelope(
        f"{SWARM_PROMPT_PREFIX}{prompt}"
    ),
}


@pytest.fixture
def wrapped_prompt_routes(tmp_path, monkeypatch):
    index = SessionSearchIndex(tmp_path / "search.db")
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: index)
    monkeypatch.setattr("src.session.search.get_shared_index", lambda: index)
    service = SessionService(
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(),
        runs_dir=tmp_path / "runs",
    )
    from src.providers import chat

    class OwnedTitleProvider:
        def chat(self, messages, timeout):
            return SimpleNamespace(content=GENERATED_TITLE)

        def close(self):
            pass

    monkeypatch.setattr(chat, "ChatLLM", OwnedTitleProvider)
    host = SimpleNamespace(
        require_auth=lambda: None,
        require_event_stream_auth=lambda: None,
        _get_session_service=lambda: service,
        _validate_path_param=lambda value, kind: None,
    )
    # This is the route module's documented host-composition boundary. Actual
    # route, persistence and index implementations remain intact.
    monkeypatch.setitem(sys.modules, "api_server", host)
    app = FastAPI()
    register_sessions_routes(app)
    try:
        yield service, index, app
    finally:
        index.close()


def _seed_web_chat_session(service, index, *, wrapped: str, title: str):
    """Reproduce what the web composer persists: raw title, wrapped message."""
    from src.session.models import Message

    session = service.create_session(title=title[:50])
    # The auto-title route reads a real stored user message; it is admitted
    # directly so no agent or provider runs during setup.
    service.store.append_message(
        Message(session_id=session.session_id, role="user", content=wrapped)
    )
    index.index_message(session.session_id, "user", wrapped)
    service.store.append_message(
        Message(
            session_id=session.session_id,
            role="assistant",
            content="Realized vol is 18% annualized over the trailing quarter.",
        )
    )
    return session


def _auto_title_endpoint(app):
    return next(
        r.endpoint for r in app.routes if r.path == "/sessions/{session_id}/title/auto"
    )


@pytest.mark.parametrize("wrapper", sorted(WRAPPERS))
def test_auto_title_rewrites_session_created_with_wrapped_first_message(
    wrapped_prompt_routes, wrapper
):
    service, index, app = wrapped_prompt_routes
    session = _seed_web_chat_session(
        service,
        index,
        wrapped=WRAPPERS[wrapper](RAW_PROMPT),
        title=RAW_PROMPT,
    )

    result = asyncio.run(_auto_title_endpoint(app)(session.session_id))

    assert result["status"] == "updated", (
        f"{wrapper} wrapper: route reported {result['status']!r} with title "
        f"{result['title']!r}; the stored title is the raw first-prompt prefix, "
        "not a manual rename"
    )
    assert result["title"] == GENERATED_TITLE
    assert service.store.get_session(session.session_id).title == GENERATED_TITLE


def test_auto_title_rewrites_long_wrapped_prompt_truncated_at_fifty(
    wrapped_prompt_routes,
):
    """The create-time title is the raw prompt cut at 50 chars, not the wrapper."""
    service, index, app = wrapped_prompt_routes
    long_prompt = (
        "analyse portfolio volatility across every equity sleeve and report drawdowns"
    )
    assert len(long_prompt) > 50
    session = _seed_web_chat_session(
        service,
        index,
        wrapped=f"{SWARM_PROMPT_PREFIX}{long_prompt}",
        title=long_prompt,
    )
    assert service.store.get_session(session.session_id).title == long_prompt[:50]

    result = asyncio.run(_auto_title_endpoint(app)(session.session_id))

    assert result["status"] == "updated", result
    assert service.store.get_session(session.session_id).title == GENERATED_TITLE


@pytest.mark.parametrize("wrapper", sorted(WRAPPERS))
def test_auto_title_preserves_manual_rename_on_wrapped_session(
    wrapped_prompt_routes, wrapper
):
    """The documented guarantee: a real rename is never overwritten."""
    service, index, app = wrapped_prompt_routes
    session = _seed_web_chat_session(
        service,
        index,
        wrapped=WRAPPERS[wrapper](RAW_PROMPT),
        title=RAW_PROMPT,
    )
    patch = next(
        r.endpoint
        for r in app.routes
        if r.path == "/sessions/{session_id}" and "PATCH" in r.methods
    )
    asyncio.run(
        patch(session.session_id, UpdateSessionRequest(title="Manual protected title"))
    )

    result = asyncio.run(_auto_title_endpoint(app)(session.session_id))

    assert result["status"] == "kept", result
    assert result["title"] == "Manual protected title"
    assert (
        service.store.get_session(session.session_id).title == "Manual protected title"
    )

