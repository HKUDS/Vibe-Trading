"""Session history regressions for completed-attempt tool trails."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src.session.events import EventBus
from src.session.models import Attempt, Message, Session
from src.session.service import SessionService
from src.session.store import SessionStore
from src.session.thread import ThreadLog


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

    async def _run_with_agent(attempt, *args, **kwargs):
        del args, kwargs
        # The display trail is projected from the turn's thread items.
        thread = ThreadLog(
            service.store.thread_path(attempt.session_id), clock=lambda: 1_785_342_400.0
        )
        thread.append("turn_start", attempt.attempt_id, prompt=attempt.prompt)
        thread.append("user", attempt.attempt_id, content=attempt.prompt, llm_content=attempt.prompt)
        thread.append("assistant", attempt.attempt_id, content=None, phase="commentary", tool_calls=[
            {"id": "call-market-1", "type": "function",
             "function": {"name": "get_market_data", "arguments": '{"symbol": "AAPL"}'}},
        ])
        thread.append("tool_result", attempt.attempt_id, tool_call_id="call-market-1",
                      name="get_market_data", content="AAPL 195.00", status="ok", elapsed_ms=125)
        thread.append("assistant", attempt.attempt_id, content="AAPL is trading near 195.", phase="final")
        return {"status": "success", "content": "AAPL is trading near 195."}

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


@pytest.mark.parametrize(
    ("run_status", "attempt_status"),
    [("failed", "failed"), ("cancelled", "cancelled")],
)
def test_unfinished_attempt_keeps_its_tool_trail(
    tmp_path: Path, monkeypatch, run_status: str, attempt_status: str
) -> None:
    """A failed run's steps survive a reload; they used to be saved as ``[]``.

    The history then read "failed · 0 steps" for a run that stopped on
    ``no_progress`` after eight rounds of tool calls.
    """
    service = _service(tmp_path, monkeypatch)
    session = Session(session_id="abcdef012346", title="failed trail")
    service.store.create_session(session)
    attempt = Attempt(attempt_id="attempt00002", session_id=session.session_id, prompt="Compare games")
    service.store.create_attempt(attempt)
    trail = [
        {"tool": "get_financial_statements", "status": "ok", "arguments": {"code": "002555.SZ"},
         "call_id": "call-1", "timestamp": 1_785_342_400_000, "preview": '{"ok": true}'},
        {"tool": "get_financial_statements", "status": "error", "arguments": {"code": "09999.HK"},
         "call_id": "call-2", "timestamp": 1_785_342_400_000, "preview": '{"status": "error"}'},
    ]

    async def _run_with_agent(attempt, *args, **kwargs):
        del args, kwargs
        thread = ThreadLog(
            service.store.thread_path(attempt.session_id), clock=lambda: 1_785_342_400.0
        )
        thread.append("turn_start", attempt.attempt_id, prompt=attempt.prompt)
        thread.append("user", attempt.attempt_id, content=attempt.prompt, llm_content=attempt.prompt)
        thread.append("assistant", attempt.attempt_id, content=None, phase="commentary", tool_calls=[
            {"id": "call-1", "type": "function",
             "function": {"name": "get_financial_statements", "arguments": '{"code": "002555.SZ"}'}},
            {"id": "call-2", "type": "function",
             "function": {"name": "get_financial_statements", "arguments": '{"code": "09999.HK"}'}},
        ])
        thread.append("tool_result", attempt.attempt_id, tool_call_id="call-1",
                      name="get_financial_statements", content='{"ok": true}', status="ok")
        thread.append("tool_result", attempt.attempt_id, tool_call_id="call-2",
                      name="get_financial_statements", content='{"status": "error"}', status="error")
        return {"status": run_status, "reason": "no_progress: stopped"}

    monkeypatch.setattr(service, "_run_with_agent", _run_with_agent)
    asyncio.run(service._run_attempt(session, attempt))

    stored = service.store.get_messages(session.session_id)[0]
    assert stored.metadata["status"] == attempt_status
    assert stored.tool_trail == trail


def test_run_with_agent_consolidates_tool_results_by_call_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Results finishing out of order land on their own call, through the real plumbing.

    The loop writes the turn through the recorder ``_run_with_agent`` hands it;
    the reply's trail is projected from those items when the turn ends.
    """

    class _DummyAgentLoop:
        def __init__(
            self,
            *,
            registry,
            llm,
            event_callback,
            max_iterations,
            persistent_memory,
            cancel_event=None,
            background_manager=None,
            thread_recorder=None,
            queued_inputs=None,
            memory=None,
        ) -> None:
            del registry, llm, event_callback, max_iterations, persistent_memory, cancel_event, memory
            self._thread = thread_recorder

        def run(self, *, user_message: str, history, session_id: str):
            del history, session_id
            user = {"role": "user", "content": user_message}
            self._thread.start(prompt=user_message, message=user, model=None, provider=None)
            self._thread.assistant({"role": "assistant", "content": None, "tool_calls": [
                {"id": "call-1", "type": "function",
                 "function": {"name": "get_market_data", "arguments": '{"symbol": "AAPL"}'}},
                {"id": "call-2", "type": "function",
                 "function": {"name": "get_market_data", "arguments": '{"symbol": "MSFT"}'}},
            ]}, phase="commentary")
            self._thread.tool_result(
                {"role": "tool", "tool_call_id": "call-2", "name": "get_market_data", "content": "MSFT"},
                status="ok", elapsed_ms=20,
            )
            self._thread.tool_result(
                {"role": "tool", "tool_call_id": "call-1", "name": "get_market_data",
                 "content": "AAPL unavailable"},
                status="error", elapsed_ms=10,
            )
            self._thread.assistant({"role": "assistant", "content": "done"}, phase="final")
            return {"status": "success", "content": "done"}

        def cancel(self) -> None:
            pass

    monkeypatch.setattr("src.tools.build_registry", lambda **kwargs: object())
    llm = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr("src.providers.chat.ChatLLM", lambda: llm)
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
    session = Session(session_id="abcdef012345", title="consolidate")
    service.store.create_session(session)
    attempt = Attempt(session_id=session.session_id, prompt="compare")
    service.store.create_attempt(attempt)

    asyncio.run(service._run_attempt(session, attempt))

    reply = service.store.get_messages(session.session_id)[-1]
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
        for entry in reply.tool_trail
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
