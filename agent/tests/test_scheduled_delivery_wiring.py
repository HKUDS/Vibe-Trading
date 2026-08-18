"""The outbox's two collaborators, wired to the real runtime (#942).

The executor is deliberately ignorant of both the session runtime and the
channel runtime; these are the adapters that connect them, and the properties
that matter are that a briefing is read only once its run is terminal, and
that a delivery which cannot happen raises instead of reporting success.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import scheduled_routes
from src.scheduled_research.models import DeliveryStatus, ScheduledResearchJob
from src.scheduled_research.store import ScheduledResearchJobStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScheduledResearchJobStore:
    isolated = ScheduledResearchJobStore(path=tmp_path / "scheduled_jobs.json")
    monkeypatch.setattr(scheduled_routes, "_scheduled_research_store", isolated)
    return isolated


@pytest.fixture
def client(store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _message(role: str, content: str, status: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        role=role, content=content, metadata={"status": status} if status else {}
    )


def _with_messages(monkeypatch: pytest.MonkeyPatch, messages: list[SimpleNamespace]) -> None:
    service = SimpleNamespace(get_messages=lambda _sid, limit=50: messages)
    monkeypatch.setattr(
        api_server, "_get_session_service", lambda: service, raising=False
    )


def test_a_briefing_is_read_only_once_its_run_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No status on the reply means the run has not finished."""
    _with_messages(monkeypatch, [_message("user", "brief me")])
    assert scheduled_routes._read_scheduled_briefing("s1") is None

    _with_messages(
        monkeypatch,
        [_message("user", "brief me"), _message("assistant", "VERDICT: hold", "completed")],
    )
    assert scheduled_routes._read_scheduled_briefing("s1") == ("completed", "VERDICT: hold")


def test_the_briefing_is_the_reply_the_user_would_see(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The last terminal reply, so the channel and the app never disagree."""
    _with_messages(
        monkeypatch,
        [
            _message("assistant", "first pass", "completed"),
            _message("user", "again"),
            _message("assistant", "final answer", "completed"),
        ],
    )

    assert scheduled_routes._read_scheduled_briefing("s1") == ("completed", "final answer")


def test_a_failed_run_reports_its_status_rather_than_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_messages(monkeypatch, [_message("assistant", "could not finish", "failed")])

    status, _text = scheduled_routes._read_scheduled_briefing("s1")
    assert status == "failed"


@pytest.mark.parametrize(
    "manager, channel, target, expected",
    [
        (None, "telegram", "chat-1", "channel runtime is not running"),
        (SimpleNamespace(get_channel=lambda _n: None), "telegram", "chat-1", "not configured"),
        (
            SimpleNamespace(get_channel=lambda _n: SimpleNamespace()),
            "telegram",
            None,
            "no delivery target",
        ),
    ],
)
def test_a_delivery_that_cannot_happen_raises(
    monkeypatch: pytest.MonkeyPatch, manager, channel, target, expected
) -> None:
    """Silence here would record a briefing as delivered that never was sent."""
    monkeypatch.setattr(api_server, "_channel_manager", manager, raising=False)

    with pytest.raises(RuntimeError, match=expected):
        asyncio.run(scheduled_routes._send_scheduled_briefing(channel, target, "text"))


def test_create_accepts_a_delivery_channel_and_reports_its_state(
    client: TestClient, store: ScheduledResearchJobStore
) -> None:
    response = client.post(
        "/scheduled-runs",
        json={
            "prompt": "pre-open scan",
            "schedule": "60000",
            "delivery_channel": "telegram",
            "delivery_target": "chat-9",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["delivery_channel"] == "telegram"
    assert body["delivery_target"] == "chat-9"
    assert body["delivery_status"] == "none"

    stored = store.get(body["id"])
    assert stored.delivery_channel == "telegram"
    assert stored.delivery.status is DeliveryStatus.NONE


def test_a_job_without_delivery_is_unchanged_on_the_wire(
    client: TestClient, store: ScheduledResearchJobStore
) -> None:
    """Every job that existed before this feature keeps its exact behaviour."""
    response = client.post("/scheduled-runs", json={"prompt": "p", "schedule": "60000"})

    body = response.json()
    assert body["delivery_channel"] is None
    assert body["delivery_status"] == "none"
    assert store.get(body["id"]).delivery_channel is None
