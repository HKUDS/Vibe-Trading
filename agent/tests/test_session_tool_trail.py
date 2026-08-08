"""Session history regressions for completed-attempt tool trails."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

import api_server
from src.session.events import EventBus
from src.session.models import Attempt, Message, Session
from src.session.service import SessionService
from src.session.store import SessionStore


class _DummyIndex:
    def index_session(self, session_id: str, title: str) -> None:
        del session_id, title

    def index_message(self, session_id: str, role: str, content: str) -> None:
        del session_id, role, content


def _service(tmp_path: Path, monkeypatch) -> SessionService:
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    return SessionService(
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(),
        runs_dir=tmp_path / "runs",
    )


def test_completed_attempt_tool_trail_round_trips_through_history_endpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _service(tmp_path, monkeypatch)
    session = Session(session_id="abcdef012345", title="tool trail")
    service.store.create_session(session)
    attempt = Attempt(
        attempt_id="attempt00001",
        session_id=session.session_id,
        prompt="Inspect AAPL",
    )
    service.store.create_attempt(attempt)
    expected_trail = [
        {
            "tool": "get_market_data",
            "status": "ok",
            "arguments": {"symbol": "AAPL"},
            "elapsed_ms": 125,
            "preview": "AAPL 195.00",
            "call_id": "call-market-1",
            "timestamp": 1_785_342_400_000,
        }
    ]

    async def _run_with_agent(*args, **kwargs):
        del args, kwargs
        return {
            "status": "success",
            "content": "AAPL is trading near 195.",
            "tool_trail": expected_trail,
        }

    monkeypatch.setattr(service, "_run_with_agent", _run_with_agent)
    asyncio.run(service._run_attempt(session, attempt))

    monkeypatch.setattr(api_server, "_get_session_service", lambda: service)
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    response = client.get(f"/sessions/{session.session_id}/messages")

    assert response.status_code == 200
    stored = service.store.get_messages(session.session_id)[0]
    assert isinstance(stored, Message)
    assert stored.tool_trail == expected_trail
    payload = response.json()
    assert len(payload) == 1
    metadata = payload[0].pop("metadata")
    assert metadata["status"] == "completed"
    assert isinstance(metadata["elapsed_ms"], int)
    assert metadata["elapsed_ms"] >= 0
    assert payload == [
        {
            "message_id": stored.message_id,
            "session_id": session.session_id,
            "role": "assistant",
            "content": "AAPL is trading near 195.",
            "created_at": stored.created_at,
            "linked_attempt_id": attempt.attempt_id,
            "tool_trail": expected_trail,
        }
    ]


def test_run_with_agent_consolidates_tool_events_by_call_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class _DummyAgentLoop:
        def __init__(
            self,
            *,
            registry,
            llm,
            event_callback,
            max_iterations,
            persistent_memory,
        ) -> None:
            del registry, llm, max_iterations, persistent_memory
            self._event_callback = event_callback

        def run(self, *, user_message: str, history, session_id: str):
            del user_message, history, session_id
            self._event_callback(
                "tool_call",
                {
                    "tool": "get_market_data",
                    "call_id": "call-1",
                    "arguments": {"symbol": "AAPL"},
                },
            )
            self._event_callback(
                "tool_call",
                {
                    "tool": "get_market_data",
                    "call_id": "call-2",
                    "arguments": {"symbol": "MSFT"},
                },
            )
            self._event_callback(
                "tool_result",
                {
                    "tool": "get_market_data",
                    "call_id": "call-2",
                    "status": "ok",
                    "elapsed_ms": 20,
                    "preview": "MSFT",
                },
            )
            self._event_callback(
                "tool_result",
                {
                    "tool": "get_market_data",
                    "call_id": "call-1",
                    "status": "error",
                    "elapsed_ms": 10,
                    "preview": "AAPL unavailable",
                },
            )
            return {"status": "success", "content": "done"}

        def cancel(self) -> None:
            pass

    monkeypatch.setattr("src.tools.build_registry", lambda **kwargs: object())
    monkeypatch.setattr("src.providers.chat.ChatLLM", lambda: object())
    monkeypatch.setattr("src.memory.persistent.PersistentMemory", lambda: object())
    monkeypatch.setattr("src.agent.loop.AgentLoop", _DummyAgentLoop)
    monkeypatch.setattr(
        "src.config.loader.load_runtime_agent_config",
        lambda overrides=None: object(),
    )
    monkeypatch.setattr(
        "src.config.loader.sanitize_session_overrides",
        lambda overrides: dict(overrides),
    )
    service = _service(tmp_path, monkeypatch)
    attempt = Attempt(session_id="abcdef012345", prompt="compare")

    result = asyncio.run(
        service._run_with_agent(attempt, messages=[], session_config={})
    )

    assert [
        {
            key: entry[key]
            for key in (
                "tool",
                "call_id",
                "arguments",
                "status",
                "elapsed_ms",
                "preview",
            )
        }
        for entry in result["tool_trail"]
    ] == [
        {
            "tool": "get_market_data",
            "call_id": "call-1",
            "arguments": {"symbol": "AAPL"},
            "status": "error",
            "elapsed_ms": 10,
            "preview": "AAPL unavailable",
        },
        {
            "tool": "get_market_data",
            "call_id": "call-2",
            "arguments": {"symbol": "MSFT"},
            "status": "ok",
            "elapsed_ms": 20,
            "preview": "MSFT",
        },
    ]
