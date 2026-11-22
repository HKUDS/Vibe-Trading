"""Durable item events derived from ``thread.jsonl`` (design 6.8, C6).

Item events use the thread item's seq as the cursor: a client that reconnects
with a cursor reads every recorded item after it from disk, however far back
the transient in-memory buffer has rotated.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import api_server
from src.session.event_projection import ThreadEvents, display_item
from src.session.events import EventBus, SSEEvent, cursor_from_event_id
from src.session.models import Session
from src.agent.loop_streaming import TurnStream
from src.session.service import SessionService
from src.session.store import SessionStore
from src.session.thread import ThreadLog

SESSION = "abcdef012345"
TURN = "turn00000001"
ITEM_AND_RUN = {
    "item.started", "item.delta", "item.completed",
    "run.started", "run.completed", "run.failed", "run.cancelled",
}


class _DummyIndex:
    def index_session(self, session_id: str, title: str) -> None:
        del session_id, title

    def index_message(self, session_id: str, role: str, content: str) -> None:
        del session_id, role, content


def _events(tmp_path: Path, *, buffer: int = 500, heartbeat: float = 0.05):
    store = SessionStore(tmp_path / "sessions")
    bus = EventBus(max_buffer_size=buffer, heartbeat_interval_s=heartbeat)
    return store, bus, ThreadEvents(bus, store.thread_path)

def _stream(events, iteration):
    return TurnStream(emit=lambda name, data: events.emit(SESSION, name, {**data, "attempt_id": TURN}), iteration=iteration, heartbeat_interval=lambda: 0, reasoning_interval=lambda: 0)


def _assistant_call(thread: ThreadLog, turn: str, call_id: str, args: Dict[str, Any]) -> None:
    thread.append("assistant", turn, content=None, phase="commentary", tool_calls=[
        {"id": call_id, "type": "function",
         "function": {"name": "get_market_data", "arguments": json.dumps(args)}},
    ])


def _write_turn(thread: ThreadLog, turn: str, calls: int) -> None:
    """A complete turn with ``calls`` tool round trips, a state and an inject item."""
    thread.append("turn_start", turn, prompt="go", model="m", provider="p")
    thread.append("user", turn, content="go", llm_content="<agent-state>secret</agent-state>go")
    for index in range(calls):
        _assistant_call(thread, turn, f"c{index}", {"symbol": f"S{index}"})
        thread.append("tool_result", turn, tool_call_id=f"c{index}", name="get_market_data",
                      content=f"r{index}", status="ok", elapsed_ms=1)
    thread.append("inject", turn, content="<system>keep going</system>")
    thread.append("state", turn, workspace="/tmp/run", loaded_tools=["load_tools"])
    thread.append("assistant", turn, content="done", phase="final")
    thread.append("turn_end", turn, status="completed", usage={"input_tokens": 3}, elapsed_ms=5)


def _display_seqs(thread: ThreadLog, after: int = 0) -> List[int]:
    return [item.seq for item in thread.read()
            if item.seq > after and item.type not in {"state", "inject", "checkpoint"}]


def _collect(events: ThreadEvents, session_id: str = SESSION, **kwargs) -> List[SSEEvent]:
    """Every event the stream yields until the first idle heartbeat."""

    async def run() -> List[SSEEvent]:
        out: List[SSEEvent] = []
        async for event in events.stream(session_id, **kwargs):
            if event.event_type == "heartbeat":
                break
            out.append(event)
        return out

    return asyncio.run(run())


def _completed_seqs(received: List[SSEEvent]) -> List[int]:
    return [event.data["seq"] for event in received
            if event.event_type == "item.completed" and event.data.get("seq") is not None]


# ---- Live derivation ----


def test_live_items_are_started_streamed_and_completed_with_their_seq(tmp_path: Path) -> None:
    store, bus, events = _events(tmp_path)
    thread = store.thread_log(SESSION)
    observed: list[SSEEvent] = []
    bus.add_listener(observed.append)
    events.sync(SESSION)
    thread.append("turn_start", TURN, prompt="go")
    thread.append("user", TURN, content="go", llm_content="go")

    stream1 = _stream(events, 1)
    stream1.on_text('Let me ')
    stream1.on_text('check.')
    _assistant_call(thread, TURN, "c1", {"symbol": "AAPL"})
    events.emit(SESSION, 'item.started', {"kind": 'tool.started', 'iter': 1, 'attempt_id': TURN, 'item': {'type': 'tool_result', 'name': 'get_market_data', 'tool_call_id': 'c1', 'arguments': {'symbol': 'AAPL'}}, 'live_id': "tool:" + str('c1')})
    events.emit(SESSION, 'item.delta', {"kind": 'tool.progress', 'attempt_id': TURN, 'progress': {'tool': 'get_market_data', 'call_id': 'c1', 'stage': 'fetch', 'attempt_id': TURN}, 'heartbeat': False, 'live_id': "tool:" + str('c1')})
    thread.append("tool_result", TURN, tool_call_id="c1", name="get_market_data",
                  content='{"status": "error"}', status="error", elapsed_ms=4)
    events.emit(SESSION, 'item.completed', {"kind": 'tool.failed', 'attempt_id': TURN, 'item': {'type': 'tool_result', 'name': 'get_market_data', 'tool_call_id': 'c1', 'status': 'error'}, 'live_id': "tool:" + str('c1')})

    item_events = [e for e in observed if e.event_type in ITEM_AND_RUN]
    summary = [(e.event_type, e.data["kind"] if "kind" in e.data else None, e.seq) for e in item_events]
    assert summary == [
        ("item.started", "item.started", 1),     # turn_start
        ("item.completed", "item.completed", 1),
        ("run.started", None, 1),
        ("item.started", "item.started", 2),     # user
        ("item.completed", "item.completed", 2),
        ("item.started", "item.started", None),  # live assistant response
        ("item.delta", "text.delta", None),
        ("item.delta", "text.delta", None),
        ("item.completed", "item.completed", 3),
        ("item.started", "tool.started", None),
        ("item.delta", "tool.progress", None),
        ("item.completed", "tool.failed", 4),
    ]
    assistant_live = item_events[5].data["live_id"]
    assert [e.data["delta"] for e in item_events[6:8]] == ["Let me ", "check."]
    assert item_events[8].data["live_id"] == assistant_live
    assert item_events[8].data["item"]["tool_calls"] == [
        {"id": "c1", "name": "get_market_data", "arguments": {"symbol": "AAPL"}}
    ]
    tool_live = item_events[9].data["live_id"]
    assert item_events[9].data["item"]["tool_call_id"] == "c1"
    assert item_events[10].data["live_id"] == tool_live
    assert item_events[11].data["live_id"] == tool_live
    assert item_events[11].data["item"]["status"] == "error"
    assert [e.event_id for e in item_events if e.seq is not None] == [
        "item-1-started", "item-1", "item-1-run", "item-2-started", "item-2", "item-3", "item-4",
    ]


def test_removed_callbacks_are_rejected_without_publication(tmp_path: Path) -> None:
    store, bus, events = _events(tmp_path)
    thread = store.thread_log(SESSION)
    emitted = [
        ("attempt.created", {"attempt_id": TURN, "prompt": "go"}),
        ("text_delta", {"delta": "a", "iter": 1, "attempt_id": TURN}),
        ("tool_call", {"tool": "t", "arguments": {}, "iter": 1, "call_id": "c1", "attempt_id": TURN}),
        ("tool_heartbeat", {"tool": "t", "elapsed_s": 1, "call_id": "c1", "attempt_id": TURN}),
        ("tool_result", {"tool": "t", "status": "ok", "call_id": "c1", "attempt_id": TURN}),
        ("attempt.completed", {"attempt_id": TURN, "status": "completed"}),
    ]
    thread.append("turn_start", TURN, prompt="go")
    published = []
    for event_type, data in emitted:
        published.append(events.emit(SESSION, event_type, dict(data)))

    assert published == [None] * len(emitted)
    assert all(e.event_type not in {name for name, _ in emitted} for e in bus.replay(SESSION, replay_all=True))


def test_a_response_the_thread_never_recorded_is_discarded_explicitly(tmp_path: Path) -> None:
    store, bus, events = _events(tmp_path)
    thread = store.thread_log(SESSION)
    observed: list[SSEEvent] = []
    bus.add_listener(observed.append)
    events.sync(SESSION)
    thread.append("turn_start", TURN, prompt="go")
    stream1 = _stream(events, 1)
    stream1.on_text('x')
    # Iteration 1 was filtered and never recorded; iteration 2 streams anew.
    stream2 = _stream(events, 2)
    stream2.on_text('y')
    events.emit(SESSION, 'item.started', {"kind": 'tool.started', 'attempt_id': TURN, 'item': {'type': 'tool_result', 'name': 't', 'tool_call_id': 'c9'}, 'live_id': "tool:" + str('c9')})
    thread.append("turn_end", TURN, status="cancelled")
    events.emit(SESSION, "attempt.cancelled", {"attempt_id": TURN})

    item_events = [e for e in observed if e.event_type in ITEM_AND_RUN]
    started = [e.data["live_id"] for e in item_events
               if e.event_type == "item.started" and e.seq is None]
    discarded = [e.data["live_id"] for e in item_events
                 if e.event_type == "item.completed" and e.data.get("kind") == "item.discarded"]
    assert len(started) == 3
    assert sorted(discarded) == sorted(started)
    assert item_events[-1].event_type == "run.cancelled"
    assert item_events[-1].data["status"] == "cancelled"


def test_an_interrupted_turn_is_a_failed_run_with_that_status(tmp_path: Path) -> None:
    store, bus, events = _events(tmp_path)
    thread = store.thread_log(SESSION)
    events.sync(SESSION)
    thread.append("turn_start", TURN, prompt="go")
    thread.append("turn_end", TURN, status="interrupted")
    events.sync(SESSION)

    runs = [e for e in _collect(events, cursor=0) if e.event_type.startswith("run.")]
    assert [(e.event_type, e.data["status"]) for e in runs] == [
        ("run.started", "running"), ("run.failed", "interrupted"),
    ]


# ---- Display view ----


def test_display_items_hide_model_only_content_and_redact_arguments(tmp_path: Path) -> None:
    thread = ThreadLog(tmp_path / "thread.jsonl")
    thread.append("user", TURN, content="hi", llm_content="<agent-state>x</agent-state>hi")
    thread.append("assistant", TURN, content=None, phase="commentary", reasoning_content="think",
                  provider_items=[{"type": "reasoning", "encrypted_content": "opaque"}],
                  tool_calls=[{"id": "c1", "type": "function", "extra_content": {"sig": "s"},
                               "function": {"name": "broker", "arguments": json.dumps(
                                   {"symbol": "AAPL", "api_key": "sk-live-abcdef0123456789"})}}])
    thread.append("inject", TURN, content="<system>x</system>")
    thread.append("state", TURN, identity={"records": []})
    user, assistant, inject, state = thread.read()

    assert display_item(user) == {"seq": 1, "ts": user.ts, "turn_id": TURN, "type": "user", "content": "hi"}
    view = display_item(assistant)
    assert "provider_items" not in view
    assert view["reasoning_content"] == "think"
    assert view["tool_calls"][0]["arguments"]["symbol"] == "AAPL"
    assert "sk-live-abcdef0123456789" not in json.dumps(view)
    assert display_item(inject) is None
    assert display_item(state) is None


def test_durable_event_ids_name_their_cursor() -> None:
    assert cursor_from_event_id("item-7") == 7
    assert cursor_from_event_id("item-7-run") == 7
    assert cursor_from_event_id("item-7-started") == 6
    assert cursor_from_event_id("0123456789abcdef") is None
    assert cursor_from_event_id("item-0") is None
    assert cursor_from_event_id(None) is None


# ---- Resume ----


def test_resume_from_a_cursor_older_than_the_memory_buffer(tmp_path: Path) -> None:
    store, bus, events = _events(tmp_path, buffer=5)
    thread = store.thread_log(SESSION)
    events.sync(SESSION)
    _write_turn(thread, TURN, calls=12)
    events.sync(SESSION)
    received = _collect(events, cursor=3)

    assert _completed_seqs(received) == _display_seqs(thread, after=3)
    run_events = [e for e in received if e.event_type.startswith("run.")]
    assert [e.event_type for e in run_events] == ["run.completed"]
    by_seq = {e.data["seq"]: e.data["item"] for e in received if e.event_type == "item.completed"}
    assert by_seq[max(by_seq)]["type"] == "turn_end"


def test_a_durable_last_event_id_resumes_from_disk(tmp_path: Path) -> None:
    store, _bus, events = _events(tmp_path, buffer=3)
    thread = store.thread_log(SESSION)
    events.sync(SESSION)
    _write_turn(thread, TURN, calls=4)
    events.sync(SESSION)

    received = _collect(events, last_event_id="item-6")

    assert _completed_seqs(received) == _display_seqs(thread, after=6)


def test_reconnects_see_every_recorded_seq_once_while_a_writer_runs(tmp_path: Path) -> None:
    store, bus, events = _events(tmp_path, buffer=20, heartbeat=0.2)
    thread = store.thread_log(SESSION)
    events.sync(SESSION)
    total = 120
    done = threading.Event()

    def writer() -> None:
        thread.append("turn_start", TURN, prompt="go")
        for index in range(total):
            thread.append("tool_result", TURN, tool_call_id=f"c{index}", name="t",
                          content=str(index), status="ok")
            if index % 7 == 0:
                thread.append("state", TURN, loaded_tools=[str(index)])
            events.emit(SESSION, 'item.completed', {"kind": 'tool.completed', 'attempt_id': TURN, 'item': {'type': 'tool_result', 'tool_call_id': f'c{index}'}, 'live_id': "tool:" + str(f'c{index}')})
            time.sleep(0.001)
        thread.append("turn_end", TURN, status="completed")
        events.emit(SESSION, "attempt.completed", {"attempt_id": TURN})
        done.set()

    async def client() -> List[List[int]]:
        bus.set_loop(asyncio.get_running_loop())
        connections: List[List[int]] = []
        cursor = 0
        worker = threading.Thread(target=writer)
        worker.start()
        while True:
            seen: List[int] = []
            async for event in events.stream(SESSION, cursor=cursor):
                if event.event_type == "heartbeat":
                    break
                if "cursor" in event.data:
                    cursor = event.data["cursor"]
                if event.event_type == "item.completed" and event.seq is not None:
                    seen.append(event.seq)
                if len(seen) >= 9:  # Drop the connection mid-stream.
                    break
            connections.append(seen)
            if done.is_set() and not seen:
                break
        await asyncio.to_thread(worker.join)
        return connections

    connections = asyncio.run(client())
    delivered = [seq for seen in connections for seq in seen]
    assert len(connections) > 3
    assert len(delivered) == len(set(delivered))
    assert delivered == sorted(delivered)
    assert delivered == _display_seqs(thread)


def test_items_a_full_subscriber_queue_dropped_are_reread_from_disk(tmp_path: Path) -> None:
    store, _bus, events = _events(tmp_path)
    thread = store.thread_log(SESSION)
    events.sync(SESSION)
    thread.append("turn_start", TURN, prompt="go")
    events.sync(SESSION)

    async def run() -> List[int]:
        stream = events.stream(SESSION, cursor=0)
        seqs = [(await stream.__anext__()).seq]  # turn_start, from disk; now attached
        for index in range(150):  # 300 durable events into a 200-slot queue.
            thread.append("tool_result", TURN, tool_call_id=f"c{index}", name="t",
                          content="x", status="ok")
        events.sync(SESSION)
        async for event in stream:
            if event.event_type == "heartbeat":
                break
            if event.event_type == "item.completed":
                seqs.append(event.seq)
        await stream.aclose()
        return seqs

    seqs = asyncio.run(run())
    assert seqs == _display_seqs(thread)


def test_no_cursor_on_an_active_turn_gets_its_items_from_disk(tmp_path: Path) -> None:
    store, bus, events = _events(tmp_path, buffer=4)
    thread = store.thread_log(SESSION)
    events.sync(SESSION)
    _write_turn(thread, "turnprevious", calls=1)
    thread.append("turn_start", TURN, prompt="go")
    thread.append("user", TURN, content="go", llm_content="go")
    _assistant_call(thread, TURN, "c1", {"symbol": "AAPL"})
    events.sync(SESSION)
    events.emit(SESSION, 'item.started', {"kind": 'tool.started', 'attempt_id': TURN, 'item': {'type': 'tool_result', 'name': 'get_market_data', 'tool_call_id': 'c1'}, 'live_id': "tool:" + str('c1')})
    events.emit(SESSION, 'item.delta', {"kind": 'tool.progress', 'attempt_id': TURN, 'progress': {'call_id': 'c1', 'stage': 'fetch', 'attempt_id': TURN}, 'heartbeat': False, 'live_id': "tool:" + str('c1')})
    buffered = bus.replay(SESSION, replay_all=True)

    received = _collect(events, replay_all=True, active_turn_id=TURN)

    turn_seqs = [item.seq for item in thread.read() if item.turn_id == TURN]
    assert _completed_seqs(received) == turn_seqs
    # Then the buffer as before, without the item events disk already gave.
    assert received[-len([e for e in buffered if e.seq is None]):] == [e for e in buffered if e.seq is None]
    assert [e.data.get("kind") for e in received if e.event_type == "item.delta"] == ["tool.progress"]


def test_cursor_resume_replays_only_the_live_events_of_unfinished_items(tmp_path: Path) -> None:
    store, _bus, events = _events(tmp_path)
    thread = store.thread_log(SESSION)
    thread.append("turn_start", TURN, prompt="go")
    events.sync(SESSION)
    stream1 = _stream(events, 1)
    stream1.on_text('done one')
    _assistant_call(thread, TURN, "c1", {"symbol": "AAPL"})
    events.emit(SESSION, 'item.started', {"kind": 'tool.started', 'attempt_id': TURN, 'item': {'type': 'tool_result', 'name': 'get_market_data', 'tool_call_id': 'c1'}, 'live_id': "tool:" + str('c1')})
    stream2 = _stream(events, 2)
    stream2.on_text('still going')

    received = _collect(events, cursor=1)

    assert _completed_seqs(received) == [2]
    completed = next(e for e in received if e.event_type == "item.completed")
    finished_live = completed.data["live_id"]
    live = [e for e in received if e.event_type in {"item.started", "item.delta"} and e.seq is None]
    assert finished_live not in {e.data["live_id"] for e in live}
    assert [e.data.get("delta") for e in live if e.event_type == "item.delta"] == ["still going"]
    assert {e.data["item"]["type"] for e in live if e.event_type == "item.started"} == {
        "tool_result", "assistant",
    }


def test_resume_uses_the_thread_cursor_instead_of_legacy_buffer_replay(tmp_path: Path) -> None:
    store, bus, events = _events(tmp_path)
    thread = store.thread_log(SESSION)
    events.sync(SESSION)
    thread.append("turn_start", TURN, prompt="go")
    events.sync(SESSION)
    received = _collect(events, cursor=0)
    assert [event.event_type for event in received] == ["item.completed", "run.started"]
    assert _collect(events) == []


# ---- Service integration ----


class _ScriptedLoop:
    """AgentRuntime stand-in that streams and records like the real loop."""

    def __init__(self, *, registry, llm, event_callback, max_iterations, persistent_memory,
                 cancel_event=None, background_manager=None, thread_recorder=None,
                 queued_inputs=None, memory=None) -> None:
        del registry, llm, max_iterations, persistent_memory, cancel_event, background_manager, memory
        self._emit = event_callback
        self._thread = thread_recorder

    def run(self, *, user_message: str, history, session_id: str):
        del history, session_id
        self._emit("goal.updated", {"goal": {"goal_id": "goal-test"}})
        self._emit("swarm.started", {"run_id": "swarm-test"})
        self._thread.start(prompt=user_message, message={"role": "user", "content": user_message},
                           model=None, provider=None)
        self._emit('item.delta', {"kind": 'text.delta', 'delta': 'Checking.', 'iter': 1})
        self._thread.assistant({"role": "assistant", "content": "Checking.", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "get_market_data", "arguments": '{"symbol": "AAPL"}'}},
        ]}, phase="commentary")
        self._emit('item.started', {"kind": 'tool.started', 'iter': 1, 'item': {'type': 'tool_result', 'name': 'get_market_data', 'tool_call_id': 'c1', 'arguments': {'symbol': 'AAPL'}}, 'live_id': "tool:" + str('c1')})
        self._thread.tool_result({"role": "tool", "tool_call_id": "c1", "name": "get_market_data",
                                  "content": "AAPL 195"}, status="ok", elapsed_ms=3)
        self._emit('item.completed', {"kind": 'tool.completed', 'item': {'type': 'tool_result', 'name': 'get_market_data', 'tool_call_id': 'c1', 'status': 'ok'}, 'live_id': "tool:" + str('c1')})
        self._emit('item.delta', {"kind": 'text.delta', 'delta': 'AAPL is 195.', 'iter': 2, 'phase': 'final'})
        self._thread.assistant({"role": "assistant", "content": "AAPL is 195."}, phase="final")
        return {"status": "success", "content": "AAPL is 195."}

    def cancel(self) -> None:
        pass


def _service(tmp_path: Path, monkeypatch, *, heartbeat: float = 30.0) -> SessionService:
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    return SessionService(
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(heartbeat_interval_s=heartbeat),
        runs_dir=tmp_path / "runs",
    )


def _patch_agent(monkeypatch) -> None:
    monkeypatch.setattr("src.tools.build_registry", lambda **kwargs: object())
    llm = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr("src.providers.chat.ChatLLM", lambda: llm)
    monkeypatch.setattr("src.memory.persistent.PersistentMemory", lambda: object())
    monkeypatch.setattr("src.agent.runtime.AgentRuntime", _ScriptedLoop)
    monkeypatch.setattr("src.config.loader.load_runtime_agent_config", lambda overrides=None: object())
    monkeypatch.setattr("src.config.loader.sanitize_session_overrides", lambda overrides: dict(overrides))


def test_a_service_turn_emits_only_item_and_run_events(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_agent(monkeypatch)
    service = _service(tmp_path, monkeypatch)
    observed: list[SSEEvent] = []
    service.event_bus.add_listener(observed.append)
    session = service.create_session(title="kernel")

    async def run() -> None:
        result = await service.send_message(session.session_id, "price of AAPL")
        await service._active_tasks[session.session_id]
        assert result["attempt_id"]

    asyncio.run(run())
    events = [event for event in observed if event.session_id == session.session_id]
    assert not {e.event_type for e in events} & {
        "attempt.created", "attempt.started", "text_delta", "tool_call",
        "tool_result", "attempt.completed",
    }
    order = [e.event_type for e in events]
    assert "run.completed" in order
    assert "goal.updated" in order and "swarm.started" in order
    completed = [e.data["item"] for e in events if e.event_type == "item.completed" and e.seq]
    assert [item["type"] for item in completed] == [
        "turn_start", "user", "assistant", "tool_result", "assistant", "turn_end",
    ]
    assert any(e.data.get("kind") == "tool.completed" for e in events)
    thread_seqs = _display_seqs(service.store.thread_log(session.session_id))
    assert [e.seq for e in events if e.event_type == "item.completed" and e.seq] == thread_seqs


# ---- HTTP ----


def _frames(client: TestClient, url: str, closer: threading.Timer, headers=None) -> list:
    frames: list = []
    event_type, event_id = "", None
    closer.start()
    with client.stream("GET", url, headers=headers or {}) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("id: "):
                event_id = line[len("id: "):]
            elif line.startswith("event: "):
                event_type = line[len("event: "):]
            elif line.startswith("data: "):
                frames.append((event_id, event_type, json.loads(line[len("data: "):])))
                event_id = None
    return frames


def _seed_session(tmp_path: Path, monkeypatch) -> tuple[SessionService, Session, ThreadLog]:
    first = _service(tmp_path, monkeypatch)
    session = first.create_session(title="history")
    thread = first.store.thread_log(session.session_id)
    _write_turn(thread, "turnprevious", calls=3)
    # A new service on the same directories: the process restarted, so the
    # event buffer is empty and only the thread on disk remains.
    service = _service(tmp_path, monkeypatch, heartbeat=0.2)
    monkeypatch.setattr(api_server, "_get_session_service", lambda: service)
    return service, session, thread


def test_event_stream_cursor_reads_items_from_disk_after_a_restart(
    tmp_path: Path, monkeypatch
) -> None:
    service, session, thread = _seed_session(tmp_path, monkeypatch)
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    closer = threading.Timer(0.5, lambda: service.event_bus.clear(session.session_id))

    frames = _frames(client, f"/sessions/{session.session_id}/events?cursor=2", closer)

    completed = [(event_id, data["seq"]) for event_id, kind, data in frames if kind == "item.completed"]
    assert [seq for _, seq in completed] == _display_seqs(thread, after=2)
    assert all(event_id == f"item-{seq}" for event_id, seq in completed)
    assert all("llm_content" not in json.dumps(data) for _, _, data in frames)

    closer = threading.Timer(0.5, lambda: service.event_bus.clear(session.session_id))
    frames = _frames(client, f"/sessions/{session.session_id}/events", closer,
                     headers={"Last-Event-ID": "item-9"})
    assert [data["seq"] for _, kind, data in frames if kind == "item.completed"] == _display_seqs(
        thread, after=9
    )


def test_thread_endpoint_pages_display_items_by_seq(tmp_path: Path, monkeypatch) -> None:
    _service_, session, thread = _seed_session(tmp_path, monkeypatch)
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    expected = _display_seqs(thread)
    last_seq = thread.read()[-1].seq

    pages, after = [], 0
    while True:
        response = client.get(f"/sessions/{session.session_id}/thread", params={"after": after, "limit": 4})
        assert response.status_code == 200
        body = response.json()
        assert body["cursor"] == last_seq
        pages.append([item["seq"] for item in body["items"]])
        if not body["has_more"]:
            break
        after = body["items"][-1]["seq"]
    assert [seq for page in pages for seq in page] == expected
    assert all(len(page) == 4 for page in pages[:-1])

    newest = client.get(f"/sessions/{session.session_id}/thread", params={"before": expected[-1], "limit": 3}).json()
    assert [item["seq"] for item in newest["items"]] == expected[-4:-1]
    assert newest["has_more"] is True

    body = client.get(f"/sessions/{session.session_id}/thread").json()
    text = json.dumps(body)
    assert "llm_content" not in text and "<agent-state>" not in text
    assert {item["type"] for item in body["items"]} == {
        "turn_start", "user", "assistant", "tool_result", "turn_end",
    }
    messages = client.get(f"/sessions/{session.session_id}/messages")
    assert messages.status_code == 200

    assert client.get("/sessions/fedcba987654/thread").status_code == 404
    assert client.get(f"/sessions/{session.session_id}/thread", params={"limit": 0}).status_code == 422


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch):
    from src.config.accessor import reset_env_config

    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")
    reset_env_config()
    yield
    reset_env_config()


def test_thread_endpoint_requires_the_same_auth_as_session_routes(
    tmp_path: Path, monkeypatch, api_key
) -> None:
    del api_key
    _service_, session, _thread = _seed_session(tmp_path, monkeypatch)
    url = f"/sessions/{session.session_id}/thread"
    for peer in (("203.0.113.10", 50000), ("127.0.0.1", 50000)):
        client = TestClient(api_server.app, client=peer)
        assert client.get(url).status_code == 401
        assert client.get(f"/sessions/{session.session_id}/messages").status_code == 401
        assert client.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get(url, params={"api_key": "secret"}).status_code == 401
        assert client.get(url, headers={"Authorization": "Bearer secret"}).status_code == 200


def test_event_stream_cursor_still_requires_stream_auth(tmp_path: Path, monkeypatch, api_key) -> None:
    del api_key
    _service_, session, _thread = _seed_session(tmp_path, monkeypatch)
    response = TestClient(api_server.app, client=("203.0.113.10", 50000)).get(
        f"/sessions/{session.session_id}/events?cursor=0"
    )
    assert response.status_code == 401


def test_historical_failure_stays_redacted_on_session_reads(tmp_path, monkeypatch):
    from src.session.models import Attempt

    service, session, thread = _seed_session(tmp_path, monkeypatch)
    tid = "12aabbccdd34"
    reason = "provider rejected api_key=private-old-detail"
    thread.append("turn_start", tid, prompt="Analyze", provider="p", model="m")
    seq = thread.read()[-1].seq
    # Write the earlier format directly, bypassing current write-time redaction.
    with thread.path.open("a", encoding="utf-8") as out:
        for i, payload in enumerate([
            {"type": "event", "name": "end", "data": {"reason": reason, "status": "error"}},
            {"type": "turn_end", "status": "failed", "error": reason,
             "summary": "Execution failed: " + reason},
        ], 1):
            out.write(json.dumps({"seq": seq + i, "turn_id": tid, "ts": 1, **payload}) + "\n")
    original = thread.path.read_bytes()
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    for endpoint in ("thread", "messages"):
        response = client.get(f"/sessions/{session.session_id}/{endpoint}")
        assert response.status_code == 200
        assert "[redacted]" in response.text and "private-old-detail" not in response.text
    assert thread.read()[-2].get("data")["reason"] == "provider rejected api_key=[redacted]"
    attempt = Attempt(session_id=session.session_id, attempt_id=tid)
    service.store.create_attempt(attempt)
    path = service.store._attempt_file(session.session_id, tid)
    path.write_text(json.dumps({**attempt.to_dict(), "status": "failed", "error": reason}))
    assert service.store.get_attempt(session.session_id, tid).error == "provider rejected api_key=[redacted]"
    assert thread.path.read_bytes() == original


def test_new_and_historical_tool_results_are_safe_at_the_thread_boundary(tmp_path, monkeypatch):
    _, session, thread = _seed_session(tmp_path, monkeypatch)
    tid = "12aabbccdd34"
    fields = dict(tool_call_id="c1", name="lookup", status="ok",
                  content='{"stdout":"ok","api_key":"fixture-private-value"}',
                  images=[{"alt": "api_key=fixture-private-value"}])
    item = thread.append("tool_result", tid, **fields)
    assert "fixture-private-value" not in thread.path.read_text()
    assert json.loads(item.get("content")) == {"stdout": "ok", "api_key": "[redacted]"}
    with thread.path.open("a", encoding="utf-8") as out:
        out.write(json.dumps({"seq": item.seq + 1, "type": "tool_result",
                              "ts": 1, "turn_id": tid, **fields}) + "\n")
    original = thread.path.read_bytes()
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    response = client.get(f"/sessions/{session.session_id}/thread")
    assert response.status_code == 200
    assert "fixture-private-value" not in response.text
    assert json.loads(thread.read()[-1].get("content"))["stdout"] == "ok"
    assert thread.path.read_bytes() == original
