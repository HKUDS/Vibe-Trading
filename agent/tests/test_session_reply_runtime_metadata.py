from __future__ import annotations

import asyncio
from pathlib import Path

from src.session.events import EventBus
from src.session.models import Attempt, Session
from src.session.service import SessionService
from src.session.store import SessionStore


class _DummyIndex:
    def index_session(self, session_id: str, title: str) -> None:
        del session_id, title

    def index_message(self, session_id: str, role: str, content: str) -> None:
        del session_id, role, content


def test_completed_reply_persists_runtime_identity_and_elapsed_time(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    store = SessionStore(tmp_path / "sessions")
    event_bus = EventBus()
    service = SessionService(
        store=store, event_bus=event_bus, runs_dir=tmp_path / "runs"
    )
    session = Session(title="runtime metadata")
    store.create_session(session)
    attempt = Attempt(session_id=session.session_id, prompt="hello")

    async def _fake_run(*args, **kwargs):
        del args, kwargs
        return {
            "status": "success",
            "content": "done",
            "run_dir": str(tmp_path / "runs" / "run-1"),
            "provider": "deepseek",
            "configured_model": "deepseek-v4-flash",
            "model": "deepseek-v4-flash-202607",
            "model_source": "provider_response",
            "reasoning_effort": "high",
        }

    monkeypatch.setattr(service, "_run_with_agent", _fake_run)

    asyncio.run(service._run_attempt(session, attempt))

    reply = store.get_messages(session.session_id)[-1]
    assert reply.metadata["provider"] == "deepseek"
    assert reply.metadata["configured_model"] == "deepseek-v4-flash"
    assert reply.metadata["model"] == "deepseek-v4-flash-202607"
    assert reply.metadata["model_source"] == "provider_response"
    assert reply.metadata["reasoning_effort"] == "high"
    assert isinstance(reply.metadata["elapsed_ms"], int)
    assert reply.metadata["elapsed_ms"] >= 0

    terminal = event_bus.replay(session.session_id, replay_all=True)[-1]
    assert terminal.event_type == "attempt.completed"
    assert terminal.data["model"] == "deepseek-v4-flash-202607"
    assert terminal.data["elapsed_ms"] == reply.metadata["elapsed_ms"]
