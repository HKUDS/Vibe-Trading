"""Messages sent while a turn runs wait and join the conversation in order.

These drive the real ``SessionService`` -> ``AgentLoop`` -> ``thread.jsonl``
path with a scripted offline model, as ``test_session_conversation_kernel``
does. A message is sent mid-turn from inside a tool (or the model call) by
scheduling ``send_message`` on the service's event loop, which is exactly what
an HTTP request arriving at that moment does.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api.sessions_routes import MAX_MESSAGE_CHARS
from src.agent.tools import BaseTool, ToolRegistry
from src.session.events import EventBus, SSEEvent
from src.session.pending_inputs import (
    MAX_PENDING_INPUTS,
    PENDING_INPUTS_FILENAME,
    PendingInputQueue,
)
from src.session.service import SessionBusyError, SessionService
from src.session.store import SessionStore


class _DummyIndex:
    def index_session(self, session_id: str, title: str) -> None:
        del session_id, title

    def index_message(self, session_id: str, role: str, content: str) -> None:
        del session_id, role, content


class _NoMemory:
    snapshot = ""

    def find_relevant(self, *args: Any, **kwargs: Any) -> list:
        del args, kwargs
        return []


class _LookupTool(BaseTool):
    name = "lookup"
    description = "Read a value (offline double)."
    parameters = {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}
    is_readonly = True
    repeatable = True

    def __init__(self, during: Callable[[dict], None]) -> None:
        self.during = during

    def execute(self, **kwargs: Any) -> str:
        self.during(kwargs)
        return json.dumps({"ok": True, "value": f"value-of-{kwargs['key']}"})


class _ProcessDied(BaseException):
    """Stands in for the process dying."""


def _call(call_id: str, name: str, **arguments: Any) -> SimpleNamespace:
    return SimpleNamespace(id=call_id, name=name, arguments=arguments)


def _response(content: str = "", calls: tuple = ()) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        reasoning_content=None,
        has_tool_calls=bool(calls),
        tool_calls=list(calls),
        usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
    )


class _PolicyLLM:
    model_name = "offline"

    def __init__(self, policy: Callable[..., SimpleNamespace]) -> None:
        self.policy = policy
        self.requests: list[list] = []

    def stream_chat(self, messages: list, tools=None, on_text_chunk=None, **kwargs: Any):
        del tools, kwargs
        self.requests.append(copy.deepcopy(messages))
        return self.policy(self, messages, on_text_chunk)

    def chat(self, messages: list, **kwargs: Any) -> SimpleNamespace:
        del messages, kwargs
        return SimpleNamespace(content="SUMMARY", usage_metadata=None)

    async def aclose(self) -> None:
        return None


class _Harness:
    """A service, its event loop and a way to send from inside a turn."""

    def __init__(self, tmp_path: Path, monkeypatch, policy, *, during=lambda kwargs: None) -> None:
        self.tmp_path = tmp_path
        self.llm = _PolicyLLM(policy)
        self.registry_kwargs: list[dict] = []
        self.loop: asyncio.AbstractEventLoop | None = None
        self.events: list[SSEEvent] = []
        lookup = _LookupTool(during)

        def build_registry(**kwargs: Any) -> ToolRegistry:
            self.registry_kwargs.append(kwargs)
            registry = ToolRegistry()
            registry.register(lookup)
            return registry

        monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
        monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
        monkeypatch.setattr("src.tools.build_registry", build_registry)
        monkeypatch.setattr("src.providers.chat.ChatLLM", lambda: self.llm)
        monkeypatch.setattr("src.memory.persistent.PersistentMemory", _NoMemory)
        monkeypatch.setattr("src.config.loader.load_runtime_agent_config", lambda overrides=None: object())
        monkeypatch.setattr("src.config.loader.sanitize_session_overrides", lambda overrides: dict(overrides))
        self.service = self.restart()
        self.sid = self.service.create_session(title="queue").session_id

    def restart(self) -> SessionService:
        bus = EventBus()
        bus.add_listener(self.events.append)
        self.service = SessionService(
            store=SessionStore(self.tmp_path / "sessions"), event_bus=bus, runs_dir=self.tmp_path / "runs",
        )
        return self.service

    def send_from_turn(self, text: str, **kwargs: Any) -> dict:
        """Send while the turn runs: called on the agent thread."""
        future = asyncio.run_coroutine_threadsafe(
            self.service.send_message(self.sid, text, queue_if_busy=True, **kwargs), self.loop,
        )
        return future.result(timeout=10)

    async def run_until_idle(self, text: str, **kwargs: Any) -> dict:
        """Send, then wait for every turn the send leads to."""
        self.loop = asyncio.get_running_loop()
        sent = await self.service.send_message(self.sid, text, **kwargs)
        await self.wait_idle()
        return sent

    async def wait_idle(self) -> None:
        while (task := self.service._active_tasks.get(self.sid)) is not None:
            await task

    def items(self) -> list:
        return self.service.store.thread_log(self.sid).read()

    def users(self) -> list:
        return [(item.turn_id, item.get("content")) for item in self.items() if item.type == "user"]

    def item_events(self, kind: str) -> list[dict]:
        return [e.data for e in self.events if e.session_id == self.sid and e.data.get("kind") == kind]


# ---------------------------------------------------------------------------
# Delivery into the running turn
# ---------------------------------------------------------------------------


def test_input_queued_mid_tool_reaches_the_next_model_call_once(tmp_path, monkeypatch):
    receipts: list = []

    def during(kwargs):
        if kwargs["key"] == "us" and not receipts:
            # A caller that did not opt in is still refused, and queues nothing.
            with pytest.raises(SessionBusyError):
                asyncio.run_coroutine_threadsafe(
                    harness.service.send_message(harness.sid, "refused"), harness.loop
                ).result(timeout=10)
            receipts.append(harness.send_from_turn("Also check HK"))

    def policy(llm, messages, on_text):
        del messages, on_text
        if len(llm.requests) == 1:
            return _response(calls=(_call("c-us", "lookup", key="us"),))
        return _response(content="US and HK both checked.")

    harness = _Harness(tmp_path, monkeypatch, policy, during=during)
    sent = asyncio.run(harness.run_until_idle("Check US"))
    turn = sent["attempt_id"]

    assert receipts[0]["status"] == "queued"
    assert receipts[0]["attempt_id"] == turn and receipts[0]["position"] == 1
    # One turn, two model calls: the input joined the turn instead of
    # starting another one.
    assert len(harness.llm.requests) == 2
    second = harness.llm.requests[1]
    tool_index = next(i for i, m in enumerate(second) if m.get("tool_call_id") == "c-us")
    assert second[tool_index + 1:] == [{"role": "user", "content": "Also check HK"}]
    assert {"role": "user", "content": "Also check HK"} not in harness.llm.requests[0]

    items = harness.items()
    assert {item.turn_id for item in items} == {turn}
    assert [content for _, content in harness.users()] == ["Check US", "Also check HK"]
    queued_item = next(i for i in items if i.type == "user" and i.get("content") == "Also check HK")
    result_item = next(i for i in items if i.type == "tool_result")
    answer_item = [i for i in items if i.type == "assistant"][-1]
    assert result_item.seq < queued_item.seq < answer_item.seq
    assert queued_item.get("llm_content") == "Also check HK"
    assert harness.service.list_pending_inputs(harness.sid) == []

    rows = harness.service.get_messages(harness.sid)
    assert [(m.role, m.content) for m in rows] == [
        ("user", "Check US"), ("user", "Also check HK"), ("assistant", "US and HK both checked."),
    ]
    assert rows[1].metadata["queued_input_id"] == receipts[0]["input_id"]

    # Queued: a live user item; delivered: the recorded item completes it.
    started = [e for e in harness.item_events("item.started") if e["item"].get("status") == "queued"]
    assert len(started) == 1 and started[0]["item"]["input_id"] == receipts[0]["input_id"]
    completed = [e for e in harness.item_events("item.completed") if e["item"]["type"] == "user"
                 and e["item"]["content"] == "Also check HK"]
    assert len(completed) == 1
    assert completed[0]["live_id"] == started[0]["live_id"] and completed[0]["seq"] == queued_item.seq

    # The next turn replays the delivered input exactly once.
    asyncio.run(harness.run_until_idle("Thanks"))
    third = harness.llm.requests[-1]
    assert third.count({"role": "user", "content": "Also check HK"}) == 1


def test_two_queued_inputs_keep_their_order(tmp_path, monkeypatch):
    receipts: list = []

    def during(kwargs):
        if kwargs["key"] == "us":
            receipts.append(harness.send_from_turn("first extra"))
            receipts.append(harness.send_from_turn("second extra"))

    def policy(llm, messages, on_text):
        del messages, on_text
        if len(llm.requests) == 1:
            return _response(calls=(_call("c-us", "lookup", key="us"),))
        return _response(content="Done.")

    harness = _Harness(tmp_path, monkeypatch, policy, during=during)
    asyncio.run(harness.run_until_idle("Check US"))

    assert [r["position"] for r in receipts] == [1, 2]
    second = harness.llm.requests[1]
    assert second[-2:] == [
        {"role": "user", "content": "first extra"},
        {"role": "user", "content": "second extra"},
    ]
    assert [content for _, content in harness.users()] == ["Check US", "first extra", "second extra"]
    completed = [e["live_id"] for e in harness.item_events("item.completed") if e["item"]["type"] == "user"
                 and e["item"]["content"] in {"first extra", "second extra"}]
    started = [e["live_id"] for e in harness.item_events("item.started") if e["item"].get("status") == "queued"]
    assert completed == started


def test_input_queued_during_the_final_answer_starts_the_next_turn(tmp_path, monkeypatch):
    receipts: list = []

    def policy(llm, messages, on_text):
        if len(llm.requests) == 1:
            on_text("The answer is 1")
            receipts.append(harness.send_from_turn("And the follow-up?"))
            return _response(content="The answer is 1")
        assert messages[-1]["role"] == "user" and "And the follow-up?" in messages[-1]["content"]
        return _response(content="The follow-up is 2")

    harness = _Harness(tmp_path, monkeypatch, policy)
    sent = asyncio.run(harness.run_until_idle("What is it?"))
    first_turn = sent["attempt_id"]

    assert receipts[0]["status"] == "queued" and receipts[0]["attempt_id"] == first_turn
    assert len(harness.llm.requests) == 2
    turns = [item.turn_id for item in harness.items() if item.type == "turn_start"]
    assert len(turns) == 2 and turns[0] == first_turn
    assert harness.users() == [(first_turn, "What is it?"), (turns[1], "And the follow-up?")]
    ends = [item.get("status") for item in harness.items() if item.type == "turn_end"]
    assert ends == ["completed", "completed"]
    assert harness.service.list_pending_inputs(harness.sid) == []
    rows = harness.service.get_messages(harness.sid)
    assert [(m.role, m.content) for m in rows] == [
        ("user", "What is it?"), ("assistant", "The answer is 1"),
        ("user", "And the follow-up?"), ("assistant", "The follow-up is 2"),
    ]
    assert harness.service.store.get_session(harness.sid).last_attempt_id == turns[1]
    completed = [e for e in harness.item_events("item.completed") if e["item"]["type"] == "user"
                 and e["item"]["content"] == "And the follow-up?"]
    started = [e for e in harness.item_events("item.started") if e["item"].get("status") == "queued"]
    assert len(completed) == 1 and completed[0]["live_id"] == started[0]["live_id"]
    assert completed[0]["turn_id"] == turns[1]


def test_input_without_shell_tools_never_joins_a_turn_that_has_them(tmp_path, monkeypatch):
    def during(kwargs):
        if kwargs["key"] == "us":
            harness.send_from_turn("remote question", include_shell_tools=False)

    def policy(llm, messages, on_text):
        del on_text
        if len(llm.requests) == 1:
            return _response(calls=(_call("c-us", "lookup", key="us"),))
        return _response(content=f"answer {len(llm.requests)}")

    harness = _Harness(tmp_path, monkeypatch, policy, during=during)
    sent = asyncio.run(harness.run_until_idle("local question", include_shell_tools=True))

    assert {"role": "user", "content": "remote question"} not in harness.llm.requests[1]
    assert [kwargs["include_shell_tools"] for kwargs in harness.registry_kwargs] == [True, False]
    users = harness.users()
    assert users[0] == (sent["attempt_id"], "local question")
    assert users[1][1] == "remote question" and users[1][0] != sent["attempt_id"]


# ---------------------------------------------------------------------------
# Stop and restart drop nothing
# ---------------------------------------------------------------------------


def test_cancel_keeps_a_pending_input_reports_it_and_the_next_send_runs_it_first(tmp_path, monkeypatch):
    receipts: list = []

    def during(kwargs):
        if kwargs["key"] == "us":
            receipts.append(harness.send_from_turn("Second question"))
            harness.service.cancel_current(harness.sid)

    def policy(llm, messages, on_text):
        del on_text
        step = len(llm.requests)
        if step == 1:
            return _response(calls=(_call("c-us", "lookup", key="us"),))
        return _response(content=f"reply to {messages[-1]['content'][-15:]}")

    harness = _Harness(tmp_path, monkeypatch, policy, during=during)
    sent = asyncio.run(harness.run_until_idle("First question"))
    cancelled = sent["attempt_id"]

    assert len(harness.llm.requests) == 1
    assert harness.service.store.get_attempt(harness.sid, cancelled).status.value == "cancelled"
    assert "Second question" not in [content for _, content in harness.users()]
    pending = harness.service.list_pending_inputs(harness.sid)
    assert [(p["input_id"], p["content"], p["status"]) for p in pending] == [
        (receipts[0]["input_id"], "Second question", "queued")
    ]
    # No turn started on its own after the stop.
    assert harness.sid not in harness.service._inflight
    assert [i.turn_id for i in harness.items() if i.type == "turn_start"] == [cancelled]
    terminal = [e.data for e in harness.events if e.event_type == "attempt.cancelled"]
    assert terminal[-1]["pending_inputs"] == pending

    # The next send keeps send order: the waiting input runs first.
    async def follow_up() -> dict:
        harness.loop = asyncio.get_running_loop()
        receipt = await harness.service.send_message(harness.sid, "Third question", queue_if_busy=True)
        await harness.wait_idle()
        return receipt

    receipt = asyncio.run(follow_up())
    assert receipt["status"] == "queued" and receipt["position"] == 1
    turns = [i.turn_id for i in harness.items() if i.type == "turn_start"]
    assert len(turns) == 3 and receipt["attempt_id"] == turns[1]
    assert [content for _, content in harness.users()] == [
        "First question", "Second question", "Third question",
    ]
    assert harness.service.list_pending_inputs(harness.sid) == []


def test_discarding_a_waiting_input_removes_it_and_ends_its_live_item(tmp_path, monkeypatch):
    def during(kwargs):
        if kwargs["key"] == "us":
            receipts.append(harness.send_from_turn("never mind"))
            harness.service.cancel_current(harness.sid)

    receipts: list = []
    harness = _Harness(
        tmp_path, monkeypatch,
        lambda llm, messages, on_text: _response(calls=(_call("c-us", "lookup", key="us"),)),
        during=during,
    )
    asyncio.run(harness.run_until_idle("First question"))
    input_id = receipts[0]["input_id"]

    assert harness.service.discard_pending_input(harness.sid, input_id)["content"] == "never mind"
    assert harness.service.discard_pending_input(harness.sid, input_id) is None
    assert harness.service.list_pending_inputs(harness.sid) == []
    started = next(e for e in harness.item_events("item.started") if e["item"].get("status") == "queued")
    discarded = harness.item_events("item.discarded")
    assert [e["live_id"] for e in discarded] == [started["live_id"]]


def test_restart_keeps_a_waiting_input_and_settles_an_interrupted_delivery(tmp_path, monkeypatch):
    def during(kwargs):
        if kwargs["key"] == "us":
            harness.send_from_turn("delivered before the crash")

    def policy(llm, messages, on_text):
        del on_text
        if len(llm.requests) == 1:
            return _response(calls=(_call("c-us", "lookup", key="us"),))
        return _response(content=f"reply to {messages[-1]['content'][-12:]}")

    harness = _Harness(tmp_path, monkeypatch, policy, during=during)
    original_complete = PendingInputQueue.complete

    def die_after_the_write(self, session_id, input_id):
        raise _ProcessDied()

    # The process dies after the input reached the thread and its display
    # row, before it left the queue.
    monkeypatch.setattr(PendingInputQueue, "complete", die_after_the_write)

    async def doomed() -> str:
        harness.loop = asyncio.get_running_loop()
        sent = await harness.service.send_message(harness.sid, "Check US")
        with pytest.raises(_ProcessDied):
            await harness.service._active_tasks[harness.sid]
        return sent["attempt_id"]

    crashed = asyncio.run(doomed())
    monkeypatch.setattr(PendingInputQueue, "complete", original_complete)
    claimed = harness.service.list_pending_inputs(harness.sid)
    assert [(p["content"], p["status"]) for p in claimed] == [("delivered before the crash", "delivering")]

    # A second input whose claim was taken but whose write never happened.
    queue_path = harness.service.store.thread_path(harness.sid).parent / PENDING_INPUTS_FILENAME
    record = json.loads(queue_path.read_text(encoding="utf-8"))
    record["inputs"].append({
        "input_id": "lostclaim001", "content": "never written", "queued_at": 1.0,
        "queued_during": crashed, "include_shell_tools": False,
        "claimed_by": crashed, "claimed_after_seq": 10_000,
    })
    queue_path.write_text(json.dumps(record), encoding="utf-8")

    restarted = harness.restart()
    assert restarted.store.get_attempt(harness.sid, crashed).status.value == "interrupted"
    assert [(p["input_id"], p["status"]) for p in restarted.list_pending_inputs(harness.sid)] == [
        ("lostclaim001", "queued")
    ]
    rows = restarted.get_messages(harness.sid)
    assert [m.content for m in rows if m.role == "user"].count("delivered before the crash") == 1
    # Nothing started on its own at startup.
    assert restarted._active_tasks == {}

    async def follow_up() -> None:
        harness.loop = asyncio.get_running_loop()
        await restarted.send_message(harness.sid, "What now?", queue_if_busy=True)
        await harness.wait_idle()

    asyncio.run(follow_up())
    assert [content for _, content in harness.users()] == [
        "Check US", "delivered before the crash", "never written", "What now?",
    ]
    assert restarted.list_pending_inputs(harness.sid) == []
    last = harness.llm.requests[-1]
    assert last.count({"role": "user", "content": "delivered before the crash"}) == 1


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def test_send_route_queues_a_busy_session_with_the_same_limits(tmp_path, monkeypatch):
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    service = SessionService(
        store=SessionStore(tmp_path / "sessions"), event_bus=EventBus(), runs_dir=tmp_path / "runs",
    )
    monkeypatch.setattr(api_server, "_get_session_service", lambda: service)
    session = service.create_session(title="busy")
    session.last_attempt_id = "runningturn1"
    service.store.update_session(session)
    sid = session.session_id
    # A turn holds the session.
    service._inflight.add(sid)
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))

    response = client.post(f"/sessions/{sid}/messages", json={"content": "queued please"})
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued" and body["attempt_id"] == "runningturn1" and body["position"] == 1

    too_long = "x" * (MAX_MESSAGE_CHARS + 1)
    assert client.post(f"/sessions/{sid}/messages", json={"content": too_long}).status_code == 422
    assert client.post(f"/sessions/{sid}/messages", json={"content": ""}).status_code == 422

    listed = client.get(f"/sessions/{sid}/pending-inputs").json()
    assert [item["content"] for item in listed["items"]] == ["queued please"]

    for index in range(MAX_PENDING_INPUTS - 1):
        assert client.post(f"/sessions/{sid}/messages", json={"content": f"more {index}"}).status_code == 202
    full = client.post(f"/sessions/{sid}/messages", json={"content": "one too many"})
    assert full.status_code == 409
    assert len(client.get(f"/sessions/{sid}/pending-inputs").json()["items"]) == MAX_PENDING_INPUTS

    cancel = client.post(f"/sessions/{sid}/cancel").json()
    assert cancel["status"] == "no_active_loop"
    assert len(cancel["pending_inputs"]) == MAX_PENDING_INPUTS

    gone = client.delete(f"/sessions/{sid}/pending-inputs/{body['input_id']}")
    assert gone.status_code == 200 and gone.json()["input"]["content"] == "queued please"
    assert client.delete(f"/sessions/{sid}/pending-inputs/{body['input_id']}").status_code == 404
    assert client.get("/sessions/fedcba987654/pending-inputs").status_code == 404
