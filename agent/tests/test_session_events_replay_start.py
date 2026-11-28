"""A client joining a running attempt uses the durable thread cursor."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src.session.events import EventBus
from src.session.models import Attempt
from src.session.service import SessionService
from src.session.store import SessionStore


class _DummyIndex:
    def index_session(self, session_id: str, title: str) -> None:
        del session_id, title

    def index_message(self, session_id: str, role: str, content: str) -> None:
        del session_id, role, content


def _service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionService:
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    # The TestClient never injects a loop into the bus, so a cross-thread
    # clear() is only noticed when the subscriber's idle wait times out; keep
    # that short so each case finishes in well under a second.
    return SessionService(
        policy=ToolPolicy.from_config(get_env_config()),
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(heartbeat_interval_s=0.2),
        runs_dir=tmp_path / "runs",
    )


def _frames(
    client: TestClient, url: str, *, until_closed_by: threading.Timer
) -> list[tuple[str, dict]]:
    """Collect every (event, data) frame until the bus closes the stream.

    ``until_closed_by`` is a timer that clears the session on the bus once the
    subscription exists; the clear sentinel ends the generator so the response
    completes instead of idling on the 30 s heartbeat.
    """
    frames: list[tuple[str, dict]] = []
    event_type = ""
    until_closed_by.start()
    with client.stream("GET", url) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("event: "):
                event_type = line[len("event: ") :]
            elif line.startswith("data: "):
                frames.append((event_type, json.loads(line[len("data: ") :])))
    return frames


def test_active_replay_does_not_reannounce_legacy_attempt_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(api_server, "_get_session_service", lambda: service)
    session = service.create_session(title="long run")

    # A running attempt without thread items has no durable event to replay.
    attempt = Attempt(session_id=session.session_id, prompt="go")
    attempt.mark_running()
    service.store.create_attempt(attempt)
    session.last_attempt_id = attempt.attempt_id
    service.store.update_session(session)
    service.event_bus.clear(session.session_id)
    assert service.event_bus.replay(session.session_id, replay_all=True) == []

    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    closer = threading.Timer(0.5, lambda: service.event_bus.clear(session.session_id))
    frames = _frames(
        client,
        f"/sessions/{session.session_id}/events?replay=active",
        until_closed_by=closer,
    )

    assert frames, "stream produced no frames"
    assert all(event_type != "attempt.started" for event_type, _ in frames)


def test_active_replay_without_a_running_attempt_adds_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(api_server, "_get_session_service", lambda: service)
    session = service.create_session(title="idle")

    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    closer = threading.Timer(0.5, lambda: service.event_bus.clear(session.session_id))
    frames = _frames(
        client,
        f"/sessions/{session.session_id}/events?replay=active",
        until_closed_by=closer,
    )

    assert all(event_type != "attempt.started" for event_type, _ in frames)
