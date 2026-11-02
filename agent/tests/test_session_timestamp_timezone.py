from datetime import datetime
from pathlib import Path

from src.session.models import Attempt, Message, Session


def test_session_models_emit_timezone_aware_iso_timestamps() -> None:
    session = Session()
    message = Message()
    attempt = Attempt()

    for value in (session.created_at, session.updated_at, message.created_at, attempt.created_at):
        parsed = datetime.fromisoformat(value)
        assert parsed.tzinfo is not None

    attempt.mark_completed("done")
    assert attempt.completed_at is not None
    parsed_completed = datetime.fromisoformat(attempt.completed_at)
    assert parsed_completed.tzinfo is not None


def test_sending_a_message_keeps_updated_at_aware_and_sessions_in_order(
    monkeypatch, tmp_path: Path
) -> None:
    import asyncio
    import os
    import time

    from src.session.events import EventBus
    from src.session.service import SessionService
    from src.session.store import SessionStore

    class _NoIndex:
        def index_session(self, *args, **kwargs) -> None:
            pass

        def index_message(self, *args, **kwargs) -> None:
            pass

    # Off UTC a naive local stamp sorts by wall-clock digits, not by instant.
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    time.tzset()
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _NoIndex())
    service = SessionService(
        store=SessionStore(tmp_path / "sessions"), event_bus=EventBus(), runs_dir=tmp_path / "runs"
    )

    async def _fake_run(*args, **kwargs):
        return {"status": "success", "content": "done"}

    monkeypatch.setattr(service, "_run_with_agent", _fake_run)
    older = service.create_session(title="older")

    async def _send() -> None:
        await service.send_message(older.session_id, "hello")
        await service._active_tasks[older.session_id]

    try:
        asyncio.run(_send())
        service.create_session(title="newer")
        assert datetime.fromisoformat(service.get_session(older.session_id).updated_at).tzinfo is not None
        assert [s.title for s in service.list_sessions()] == ["newer", "older"]
    finally:
        monkeypatch.undo()
        time.tzset()
