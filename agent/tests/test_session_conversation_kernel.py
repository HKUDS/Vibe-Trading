"""The conversation, not the run, is the kernel's unit.

Every test here drives the real ``SessionService`` -> ``AgentRuntime`` ->
``thread.jsonl`` path with a scripted offline model; only the registry
builder, the LLM factory and persistent memory are replaced. The model is
scripted as a *policy*: it looks at the request it receives and only calls a
tool when the request lacks what that tool would give it, so "no repeated
search_symbol / load_tools" is an outcome of what the kernel replays, not of
a fixed script.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from src.providers.messages import INTERRUPTED_RESULT_CONTENT
from src.product.identity.ledger import IdentityLedger
from src.product.tool_loading import DeferredToolRegistry
from src.agent.tools import BaseTool, ToolRegistry
from src.session.events import EventBus
from src.session.attempts import STOPPED_MARKER
from src.session.service import SessionService
from src.session.store import SessionStore
from src.session.thread import project_turn, STOPPED_TURN_NOTES
from src.tools.read_file_tool import ReadFileTool
from src.tools.symbol_search_tool import SymbolSearchTool

MARKET_PAYLOAD = json.dumps({"ok": True, "data": {"AAPL.US": {"close": 195.0, "max_drawdown": -0.12}}})


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


class _MarketTool(BaseTool):
    name = "get_market_data"
    description = "Daily bars for canonical symbols (offline double)."
    parameters = {
        "type": "object",
        "properties": {"codes": {"type": "array", "items": {"type": "string"}}},
        "required": ["codes"],
    }
    is_readonly = True
    repeatable = True

    def __init__(self, calls: list) -> None:
        self.calls = calls

    def execute(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return MARKET_PAYLOAD


class _LookupTool(BaseTool):
    name = "lookup"
    description = "Read a value (offline double)."
    parameters = {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}
    is_readonly = True
    repeatable = True

    def __init__(self, result: Callable[[dict], str]) -> None:
        self.result = result

    def execute(self, **kwargs: Any) -> str:
        return self.result(kwargs)


class _ProcessDied(BaseException):
    """Stands in for the process dying while a tool runs."""


class _CrashTool(BaseTool):
    name = "write_report"
    description = "Write a report (offline double that dies mid-call)."
    parameters = {"type": "object", "properties": {}, "required": []}
    is_readonly = False

    def __init__(self, calls: list) -> None:
        self.calls = calls

    def execute(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        raise _ProcessDied()


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
    """Offline model: records each request, answers through ``policy``."""

    model_name = "offline"

    def __init__(self, policy: Callable[..., SimpleNamespace]) -> None:
        self.policy = policy
        self.requests: list[dict] = []
        self.summary_prompts: list[str] = []

    def stream_chat(self, messages: list, tools=None, on_text_chunk=None, **kwargs: Any):
        del kwargs
        self.requests.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        return self.policy(self, messages, tools or [], on_text_chunk)

    def chat(self, messages: list, **kwargs: Any) -> SimpleNamespace:
        del kwargs
        self.summary_prompts.append(messages[-1]["content"])
        return SimpleNamespace(content="SUMMARY-OF-EARLIER-TURNS", usage_metadata=None)

    async def aclose(self) -> None:
        return None


def _service(tmp_path: Path, monkeypatch, registry_factory, llm) -> SessionService:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    monkeypatch.setattr("src.tools.build_registry", lambda **kwargs: registry_factory())
    monkeypatch.setattr("src.providers.chat.ChatLLM", lambda: llm)
    monkeypatch.setattr("src.memory.persistent.PersistentMemory", _NoMemory)
    monkeypatch.setattr("src.config.loader.load_runtime_agent_config", lambda overrides=None: object())
    monkeypatch.setattr("src.config.loader.sanitize_session_overrides", lambda overrides: dict(overrides))
    return _restart(tmp_path)


def _restart(tmp_path: Path) -> SessionService:
    return SessionService(
        store=SessionStore(tmp_path / "sessions"), event_bus=EventBus(), runs_dir=tmp_path / "runs",
    )


async def _send(service: SessionService, session_id: str, text: str) -> str:
    sent = await service.send_message(session_id, text)
    await service._active_tasks[session_id]
    return sent["attempt_id"]


def _turn_items(service: SessionService, session_id: str, turn_id: str) -> list:
    return service.store.thread_log(session_id).turn_items(turn_id)


def _tool_names_called(items: list) -> list[str]:
    return [
        call["function"]["name"]
        for item in items
        if item.type == "assistant"
        for call in item.get("tool_calls") or []
    ]


def _tool_messages(messages: list, name: str) -> list[dict]:
    return [m for m in messages if m.get("role") == "tool" and m.get("name") == name]


# ---------------------------------------------------------------------------
# Follow-up turns reuse what the conversation already holds
# ---------------------------------------------------------------------------


def _market_registry(market_calls: list, monkeypatch):
    search = SymbolSearchTool()
    search_calls: list = []

    def resolve(**kwargs: Any) -> str:
        search_calls.append(kwargs)
        return json.dumps({"ok": True, "data": {
            "query": kwargs.get("query"), "candidates": [{"symbol": "AAPL.US"}],
            "sources": {"fixture": "ok"},
        }})

    monkeypatch.setattr(search, "execute", resolve)
    market = _MarketTool(market_calls)

    def factory() -> DeferredToolRegistry:
        base = ToolRegistry()
        base.register(search)
        base.register(market)
        return DeferredToolRegistry(base)

    return factory, search_calls


def _market_policy(llm: _PolicyLLM, messages: list, tools: list, on_text) -> SimpleNamespace:
    """Resolve and fetch only what the request does not already show."""
    del on_text
    n = len(llm.requests)
    del tools
    resolved = any("AAPL.US" in m["content"] for m in _tool_messages(messages, "search_symbol"))
    if not resolved:
        return _response(calls=(_call(f"call-{n}", "search_symbol", query="Apple"),))
    user_positions = [i for i, m in enumerate(messages) if m["role"] == "user"]
    refresh_at = max(
        (i for i in user_positions if "refresh" in str(messages[i]["content"])), default=-1,
    )
    quotes = [i for i, m in enumerate(messages) if m.get("name") == "get_market_data" and '"close"' in m["content"]]
    if not quotes or (refresh_at >= 0 and not any(i > refresh_at for i in quotes)):
        return _response(calls=(_call(f"call-{n}", "get_market_data", codes=["AAPL.US"]),))
    return _response(content="AAPL.US closed at 195.0; its max drawdown was -12%.")


def test_follow_up_turn_sees_earlier_results_and_repeats_no_resolution_or_loading(tmp_path, monkeypatch):
    market_calls: list = []
    factory, search_calls = _market_registry(market_calls, monkeypatch)
    llm = _PolicyLLM(_market_policy)
    service = _service(tmp_path, monkeypatch, factory, llm)

    async def scenario() -> None:
        session = service.create_session(title="kernel")
        sid = session.session_id
        first = await _send(service, sid, "Quote Apple")
        assert _tool_names_called(_turn_items(service, sid, first)) == [
            "search_symbol", "get_market_data",
        ]
        turn_one_requests = len(llm.requests)

        second = await _send(service, sid, "What was its max drawdown?")
        request = llm.requests[turn_one_requests]
        quotes = _tool_messages(request["messages"], "get_market_data")
        assert [m["content"] for m in quotes] == [MARKET_PAYLOAD]
        assert "get_market_data" in {t["function"]["name"] for t in request["tools"]}
        # The earlier run stays reachable: the replayed user message carries
        # its run directory in <agent-state>.
        first_run = Path(service.store.get_attempt(sid, first).run_dir).name
        assert any(first_run in str(m.get("content")) for m in request["messages"][1:-1])
        assert _tool_names_called(_turn_items(service, sid, second)) == []
        assert len(llm.requests) == turn_one_requests + 1

        third = await _send(service, sid, "Please refresh the quote.")
        third_items = _turn_items(service, sid, third)
        assert _tool_names_called(third_items) == ["get_market_data"]
        result = next(item for item in third_items if item.type == "tool_result")
        assert result.get("status") == "ok", result.get("content")
        assert len(search_calls) == 1
        assert len(market_calls) == 2
        reply = service.store.get_messages(sid)[-1]
        assert reply.metadata["status"] == "completed"
        assert reply.content.startswith("AAPL.US closed at 195.0")

    asyncio.run(scenario())


def test_runtime_rebuilt_after_restart_keeps_identity_and_loaded_tools(tmp_path, monkeypatch):
    market_calls: list = []
    factory, search_calls = _market_registry(market_calls, monkeypatch)
    llm = _PolicyLLM(_market_policy)
    service = _service(tmp_path, monkeypatch, factory, llm)

    async def first_process() -> str:
        session = service.create_session(title="restart")
        await _send(service, session.session_id, "Quote Apple")
        return session.session_id

    sid = asyncio.run(first_process())
    restarted = _restart(tmp_path)

    async def second_process() -> str:
        return await _send(restarted, sid, "Please refresh the quote.")

    turn = asyncio.run(second_process())
    items = _turn_items(restarted, sid, turn)
    assert _tool_names_called(items) == ["get_market_data"]
    assert next(i for i in items if i.type == "tool_result").get("status") == "ok"
    assert len(search_calls) == 1


# ---------------------------------------------------------------------------
# Authorization never comes from text
# ---------------------------------------------------------------------------


def test_history_text_naming_a_symbol_does_not_authorize_it(tmp_path, monkeypatch):
    market_calls: list = []
    factory, _ = _market_registry(market_calls, monkeypatch)

    def policy(llm, messages, tools, on_text):
        del messages, tools, on_text
        step = len(llm.requests)
        if step == 1:
            return _response(calls=(_call("c-nvda", "get_market_data", codes=["NVDA.US"]),))
        if step == 2:
            return _response(calls=(_call("c-aapl", "get_market_data", codes=["AAPL.US"]),))
        return _response(content="done")

    llm = _PolicyLLM(policy)
    service = _service(tmp_path, monkeypatch, factory, llm)
    session = service.create_session(title="identity")
    sid = session.session_id

    # An earlier turn whose text (user message, tool result, answer) names
    # NVDA.US and MSFT.US, while the ledger it left locked only AAPL.US.
    ledger = IdentityLedger(run_dir=tmp_path / "ledger", user_message="Quote AAPL.US")
    thread = service.store.thread_log(sid)
    thread.append("turn_start", "t0", prompt="Compare NVDA.US with AAPL.US")
    thread.append("user", "t0", content="Compare NVDA.US with AAPL.US", llm_content="Compare NVDA.US with AAPL.US")
    thread.append("assistant", "t0", content=None, phase="commentary", tool_calls=[
        {"id": "h1", "type": "function", "function": {"name": "search_symbol", "arguments": '{"query": "MSFT.US"}'}},
    ])
    thread.append("tool_result", "t0", tool_call_id="h1", name="search_symbol",
                  content='{"ok": true, "data": {"candidates": [{"symbol": "MSFT.US"}]}}', status="ok")
    thread.append("assistant", "t0", content="NVDA.US looks cheaper than AAPL.US.", phase="final")
    thread.append("state", "t0", identity=ledger.export_state(),
                  loaded_tools=["search_symbol", "load_tools", "get_market_data"])
    thread.append("turn_end", "t0", status="completed")

    async def scenario() -> str:
        return await _send(service, sid, "And now?")

    turn = asyncio.run(scenario())
    results = {i.get("tool_call_id"): i for i in _turn_items(service, sid, turn) if i.type == "tool_result"}
    refused = json.loads(results["c-nvda"].get("content"))
    assert refused["status"] == "error"
    assert refused["error_code"] == "identity_mismatch"
    assert results["c-aapl"].get("status") == "ok"
    assert [call["codes"] for call in market_calls] == [["AAPL.US"]]


def test_ledger_restores_only_its_exported_records(tmp_path):
    first = IdentityLedger(run_dir=tmp_path / "a", user_message="Quote AAPL.US")
    restored = IdentityLedger(
        run_dir=tmp_path / "b",
        user_message="and the other one",
        history=[{"role": "user", "content": "Compare NVDA.US"}],
        restored_state=first.export_state(),
    )
    assert restored.authorized_symbols == {"AAPL.US"}
    assert restored.export_state()["records"] == first.export_state()["records"]

    fresh = IdentityLedger(
        run_dir=tmp_path / "c",
        user_message="and the other one",
        history=[{"role": "user", "content": "Compare NVDA.US"}],
    )
    assert fresh.authorized_symbols == set()

    tampered = first.export_state()
    tampered["records"][0]["granted_by"] = "history"
    assert IdentityLedger(
        run_dir=tmp_path / "d", user_message="x", restored_state=tampered,
    ).authorized_symbols == set()


# ---------------------------------------------------------------------------
# Cancel, crash, restart
# ---------------------------------------------------------------------------


def _lookup_factory(extra: tuple = ()):
    lookup = _LookupTool(lambda kwargs: json.dumps({"ok": True, "value": f"value-of-{kwargs['key']}"}))

    def factory() -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(lookup)
        for tool in extra:
            registry.register(tool)
        return registry

    return factory


def test_cancel_keeps_finished_results_and_the_next_turn_sees_them_with_a_note(tmp_path, monkeypatch):
    holder: dict = {}

    def policy(llm, messages, tools, on_text):
        del tools
        step = len(llm.requests)
        if step == 1:
            return _response(calls=(_call("c-first", "lookup", key="us"),))
        if step == 2:
            on_text("Two of three markets are loaded")
            holder["service"].cancel_current(holder["sid"])
            return _response(calls=(_call("c-second", "lookup", key="hk"),))
        holder["follow_up"] = messages
        return _response(content="Continuing from the US value.")

    llm = _PolicyLLM(policy)
    service = _service(tmp_path, monkeypatch, _lookup_factory(), llm)
    session = service.create_session(title="cancel")
    holder.update(service=service, sid=session.session_id)

    async def scenario() -> tuple[str, str]:
        cancelled = await _send(service, session.session_id, "Compare three markets")
        reply = service.store.get_messages(session.session_id)[-1]
        assert reply.metadata["status"] == "cancelled"
        assert reply.content == f"Two of three markets are loaded\n\n{STOPPED_MARKER}"
        assert [e["call_id"] for e in project_turn(service.store.thread_log(reply.session_id).read(), reply.linked_attempt_id).tool_results] == ["c-first"]
        follow_up = await _send(service, session.session_id, "continue")
        return cancelled, follow_up

    cancelled, _ = asyncio.run(scenario())
    items = _turn_items(service, session.session_id, cancelled)
    assert items[-1].type == "turn_end" and items[-1].get("status") == "cancelled"
    follow_up = holder["follow_up"]
    assert [m["content"] for m in _tool_messages(follow_up, "lookup")] == [
        json.dumps({"ok": True, "value": "value-of-us"})
    ]
    assert {"role": "user", "content": STOPPED_TURN_NOTES["cancelled"]} in follow_up
    assert follow_up.index({"role": "user", "content": STOPPED_TURN_NOTES["cancelled"]}) > max(
        i for i, m in enumerate(follow_up) if m.get("tool_call_id") == "c-first"
    )


def test_crash_mid_tool_then_restart_closes_the_turn_and_keeps_finished_results(tmp_path, monkeypatch):
    crash_calls: list = []
    seen: dict = {}

    def policy(llm, messages, tools, on_text):
        del tools, on_text
        step = len(llm.requests)
        if step == 1:
            return _response(calls=(_call("c-read", "lookup", key="us"),))
        if step == 2:
            return _response(calls=(_call("c-write", "write_report"),))
        seen["messages"] = messages
        return _response(content="The US value was read; the report was not written.")

    llm = _PolicyLLM(policy)
    service = _service(tmp_path, monkeypatch, _lookup_factory((_CrashTool(crash_calls),)), llm)
    session = service.create_session(title="crash")
    sid = session.session_id

    async def doomed() -> str:
        sent = await service.send_message(sid, "Read the US value, then write the report")
        with pytest.raises(_ProcessDied):
            await service._active_tasks[sid]
        return sent["attempt_id"]

    crashed = asyncio.run(doomed())
    assert len(crash_calls) == 1
    assert service.store.get_attempt(sid, crashed).status.value == "running"
    assert service.store.thread_log(sid).open_turns() == [crashed]

    restarted = _restart(tmp_path)
    attempt = restarted.store.get_attempt(sid, crashed)
    assert attempt.status.value == "interrupted"
    items = _turn_items(restarted, sid, crashed)
    assert items[-1].type == "turn_end" and items[-1].get("status") == "interrupted"
    reply = restarted.store.get_message_for_attempt(sid, crashed)
    assert reply.metadata["status"] == "interrupted"
    assert {e["call_id"]: e["status"] for e in project_turn(service.store.thread_log(reply.session_id).read(), reply.linked_attempt_id).tool_results} == {"c-read": "ok", "c-write": "error"}

    async def follow_up() -> None:
        await _send(restarted, sid, "What happened?")

    asyncio.run(follow_up())
    messages = seen["messages"]
    read = next(m for m in messages if m.get("tool_call_id") == "c-read")
    assert read["content"] == json.dumps({"ok": True, "value": "value-of-us"})
    write = next(m for m in messages if m.get("tool_call_id") == "c-write")
    assert write["content"] == INTERRUPTED_RESULT_CONTENT
    assert {"role": "user", "content": STOPPED_TURN_NOTES["interrupted"]} in messages
    # The repair lives in the request only; the file keeps what happened.
    assert not any(
        i.type == "tool_result" and i.get("tool_call_id") == "c-write"
        for i in restarted.store.thread_log(sid).read()
    )


# ---------------------------------------------------------------------------
# Sessions recorded before thread.jsonl
# ---------------------------------------------------------------------------


def test_pre_thread_session_migrates_and_replays_after_new_turns(tmp_path, monkeypatch):
    def policy(llm, messages, tools, on_text):
        del tools, on_text
        return _response(content=f"answer {len(llm.requests)}")

    llm = _PolicyLLM(policy)
    service = _service(tmp_path, monkeypatch, _lookup_factory(), llm)
    session = service.create_session(title="legacy")
    sid = session.session_id
    run_id = "20261026_230021_46_a7d6f2"
    import json
    rows = [
        {"role": "user", "content": "backtest AAPL", "created_at": "2026-10-26T23:00:00+00:00"},
        {"role": "assistant", "content": "done", "metadata": {"run_id": run_id}, "linked_attempt_id": "old", "created_at": "2026-10-26T23:01:00+00:00"},
    ]
    directory = service.store.thread_path(sid).parent
    (directory / "messages.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    (directory / "thread_migration.json").unlink()
    assert not service.store.thread_path(sid).exists()

    async def scenario() -> None:
        await _send(service, sid, "deeper")
        await _send(service, sid, "and then?")

    asyncio.run(scenario())
    legacy = [
        {"role": "user", "content": "backtest AAPL"},
        {"role": "assistant", "content": f"[prev_run: {run_id}]\ndone"},
    ]
    first, second = llm.requests[0]["messages"], llm.requests[1]["messages"]
    assert first[1:3] == legacy
    assert first[-1]["content"].endswith("deeper")
    assert len(first) == 4
    # The second turn replays the thread after the same legacy prefix.
    assert second[1:3] == legacy
    assert second[3] == first[3]
    assert second[4] == {"role": "assistant", "content": "answer 1"}
    assert second[-1]["content"].endswith("and then?")
    assert len(second) == 6


# ---------------------------------------------------------------------------
# Display row projected from the thread
# ---------------------------------------------------------------------------


def test_projected_row_has_the_pre_change_shape_and_matches_the_live_events(tmp_path, monkeypatch):
    def policy(llm, messages, tools, on_text):
        del messages, tools, on_text
        step = len(llm.requests)
        if step == 1:
            return _response(calls=(_call("c1", "lookup", key="us"), _call("c2", "lookup", key="hk")))
        return _response(content="Both read.")

    llm = _PolicyLLM(policy)
    service = _service(tmp_path, monkeypatch, _lookup_factory(), llm)
    session = service.create_session(title="projection")
    sid = session.session_id
    events: list = []
    service.event_bus.add_listener(events.append)

    async def scenario() -> str:
        return await _send(service, sid, "Read both")

    turn = asyncio.run(scenario())
    rows = service.store.get_messages(sid)
    assert [(m.role, m.linked_attempt_id) for m in rows] == [("user", None), ("assistant", turn)]
    reply = rows[-1]
    assert reply.content == "Both read."
    assert set(reply.metadata) == {
        "run_id", "status", "elapsed_ms", "started_at",
        "provider", "configured_model", "model", "model_source", "reasoning_effort",
    }
    calls = {
        e.data["item"]["tool_call_id"]: e.data["item"]
        for e in events
        if e.event_type == "item.started" and e.data.get("kind") == "tool.started"
    }
    results = {
        e.data["item"]["tool_call_id"]: e.data["item"]
        for e in events
        if e.event_type == "item.completed" and e.data.get("kind") == "tool.completed"
    }
    assert [e["call_id"] for e in project_turn(service.store.thread_log(reply.session_id).read(), reply.linked_attempt_id).tool_results] == ["c1", "c2"]
    for entry in project_turn(service.store.thread_log(reply.session_id).read(), reply.linked_attempt_id).tool_results:
        assert set(entry) == {"tool", "status", "arguments", "timestamp", "call_id", "elapsed_ms", "preview"}
        live_call, live_result = calls[entry["call_id"]], results[entry["call_id"]]
        assert entry["tool"] == live_call["name"]
        assert entry["arguments"] == live_call["arguments"]
        assert entry["status"] == live_result["status"]
        assert entry["preview"] == live_result["content"]
        assert entry["elapsed_ms"] == live_result["elapsed_ms"]
    end = _turn_items(service, sid, turn)[-1]
    assert end.type == "turn_end" and end.get("usage")["total_tokens"] == 220


def test_phase_marks_commentary_and_final_on_items_and_events(tmp_path, monkeypatch):
    def policy(llm, messages, tools, on_text):
        del messages, tools
        if len(llm.requests) == 1:
            on_text("Checking first.")
            return _response(content="Checking first.", calls=(_call("c1", "lookup", key="us"),))
        return _response(content="Final answer.")

    llm = _PolicyLLM(policy)
    service = _service(tmp_path, monkeypatch, _lookup_factory(), llm)
    session = service.create_session(title="phase")
    events: list = []
    service.event_bus.add_listener(events.append)

    async def scenario() -> str:
        return await _send(service, session.session_id, "go")

    turn = asyncio.run(scenario())
    assistants = [i for i in _turn_items(service, session.session_id, turn) if i.type == "assistant"]
    assert [(i.get("phase"), i.get("content")) for i in assistants] == [
        ("commentary", "Checking first."), ("final", "Final answer."),
    ]
    completed_assistants = [
        e.data["item"] for e in events
        if e.event_type == "item.completed"
        and e.data.get("kind") == "item.completed"
        and e.data.get("item", {}).get("type") == "assistant"
    ]
    assert [item["phase"] for item in completed_assistants] == ["commentary", "final"]
    final_delta = [
        e.data for e in events
        if e.event_type == "item.delta" and e.data.get("kind") == "text.delta"
        and e.data.get("phase") == "final"
    ]
    assert final_delta[-1]["delta"] == "Final answer."


# ---------------------------------------------------------------------------
# Cross-turn compaction
# ---------------------------------------------------------------------------


def test_cross_turn_compaction_is_recorded_and_the_next_turn_replays_from_it(tmp_path, monkeypatch):
    def policy(llm, messages, tools, on_text):
        del messages, tools, on_text
        step = len(llm.requests)
        if step == 1:
            return _response(calls=(_call("c1", "lookup", key="us"),))
        if step == 2:
            return _response(calls=(_call("c2", "lookup", key="hk"),))
        return _response(content=f"answer {step}")

    llm = _PolicyLLM(policy)
    service = _service(tmp_path, monkeypatch, _lookup_factory(), llm)
    session = service.create_session(title="compaction")
    sid = session.session_id

    async def turn(text: str) -> str:
        return await _send(service, sid, text)

    first = asyncio.run(turn("Read US and HK"))
    second_turn_request = len(llm.requests)
    # Force the existing layers on the next turn's first request.
    monkeypatch.setattr("src.agent.tuning.TOKEN_THRESHOLD", 1, raising=False)
    second = asyncio.run(turn("Summarise"))
    monkeypatch.delattr("src.agent.tuning.TOKEN_THRESHOLD")
    asyncio.run(turn("And now?"))

    thread = service.store.thread_log(sid)
    compaction = thread.last_compaction()
    assert compaction is not None and compaction.turn_id == second
    assert llm.summary_prompts, "the summary layer did not run"
    third_request = llm.requests[-1]["messages"]
    assert third_request[1] == {"role": "user", "content": compaction.get("summary")}
    assert "SUMMARY-OF-EARLIER-TURNS" in compaction.get("summary")
    first_user = next(i for i in thread.turn_items(first) if i.type == "user")
    assert first_user.seq <= compaction.get("replaces_through_seq")
    assert not any(m.get("content") == first_user.get("llm_content") for m in third_request)
    # What the compaction kept in the second turn is still replayed after it.
    post_compaction = llm.requests[second_turn_request]["messages"]
    assert post_compaction[1]["content"] == compaction.get("summary")
    kept = {m["tool_call_id"] for m in post_compaction if m.get("role") == "tool"}
    assert kept, "the preserved tail held no tool result"
    assert kept <= {m.get("tool_call_id") for m in third_request if m.get("role") == "tool"}
    # The raw items stay in the file.
    assert first_user in thread.read()
    assert len([i for i in thread.read() if i.type == "tool_result"]) == 2


# ---------------------------------------------------------------------------
# One workspace across turns
# ---------------------------------------------------------------------------


def test_later_turn_reads_an_earlier_turns_offloaded_tool_result(tmp_path, monkeypatch):
    big = json.dumps({"ok": True, "rows": ["x" * 60 for _ in range(400)]})
    lookup = _LookupTool(lambda kwargs: big)
    reader = ReadFileTool()
    seen: dict = {}

    def factory() -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(lookup)
        registry.register(reader)
        return registry

    def policy(llm, messages, tools, on_text):
        del tools, on_text
        step = len(llm.requests)
        if step == 1:
            return _response(calls=(_call("c-big", "lookup", key="all"),))
        if step == 2:
            return _response(content="Saved.")
        if step == 3:
            receipt = json.loads(next(m for m in messages if m.get("tool_call_id") == "c-big")["content"])
            seen["receipt"] = receipt
            part = receipt["_result_file"]["parts_relative_dir"] + "/1.txt"
            return _response(calls=(_call("c-read", "read_file", path=part),))
        seen["read"] = next(m for m in messages if m.get("tool_call_id") == "c-read")["content"]
        return _response(content="Read it.")

    llm = _PolicyLLM(policy)
    service = _service(tmp_path, monkeypatch, factory, llm)
    session = service.create_session(title="workspace")
    sid = session.session_id

    async def scenario() -> tuple[str, str]:
        return await _send(service, sid, "Fetch everything"), await _send(service, sid, "Read part one")

    first, second = asyncio.run(scenario())
    first_run = Path(service.store.get_attempt(sid, first).run_dir)
    second_run = Path(service.store.get_attempt(sid, second).run_dir)
    assert first_run != second_run
    assert (second_run / "state.json").exists() and (first_run / "state.json").exists()
    payload = json.loads(seen["read"])
    assert payload["status"] == "ok", payload
    assert '"rows"' in payload["content"]


# ---------------------------------------------------------------------------
# Replayed prefix is byte-stable on the wire
# ---------------------------------------------------------------------------


def test_second_turn_request_body_repeats_the_first_turn_byte_for_byte(tmp_path, monkeypatch):
    """Captured with httpx.MockTransport through the real OpenAI-compatible adapter."""
    httpx = pytest.importorskip("httpx")
    from src.providers.adapters.openai import ChatOpenAIWithReasoning

    bodies: list[bytes] = []

    def respond(request):
        bodies.append(request.content)
        step = len(bodies)
        base = {"id": "offline", "object": "chat.completion.chunk", "created": 0, "model": "deepseek-v4-pro"}
        if step == 1:
            delta = {"tool_calls": [{"index": 0, "id": "call-lookup", "type": "function",
                                     "function": {"name": "lookup", "arguments": '{"key": "us"}'}}]}
            finish = "tool_calls"
        else:
            delta = {"content": f"Answer {step}."}
            finish = "stop"
        packets = [
            {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
            {**base, "choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}},
        ]
        text = "".join("data: " + json.dumps(p) + "\n\n" for p in packets) + "data: [DONE]\n\n"
        return httpx.Response(200, text=text, headers={"Content-Type": "text/event-stream"})

    import os
    from unittest.mock import patch

    from src.providers.chat import ChatLLM
    from src.providers.settings import resolve_config

    class _WireChatLLM(ChatLLM):
        """The real client, its SDK adapter wired to the mock transport."""

        def __init__(self) -> None:
            adapter = ChatOpenAIWithReasoning(
                model="deepseek-v4-pro", api_key="offline", base_url="https://example.invalid/v1",
                http_client=httpx.Client(transport=httpx.MockTransport(respond)),
                stream_usage=True, max_retries=0,
            )
            adapter._vibe_provider = "deepseek"
            snapshot = resolve_config(model_name="deepseek-v4-pro", environment=dict(os.environ))
            with patch("src.providers.chat.build_llm", return_value=adapter):
                super().__init__(snapshot=snapshot)

    service = _service(tmp_path, monkeypatch, _lookup_factory(), None)
    monkeypatch.setattr("src.providers.chat.ChatLLM", _WireChatLLM)
    session = service.create_session(title="bytes")

    async def scenario() -> None:
        await _send(service, session.session_id, "Read US")
        await _send(service, session.session_id, "And again")

    asyncio.run(scenario())
    assert len(bodies) == 3
    turn_one_last = json.loads(bodies[1])
    turn_two_first = json.loads(bodies[2])
    sent = turn_one_last["messages"]
    replayed = turn_two_first["messages"]
    # Everything after the system prompt (which carries the clock) is the
    # first turn's last request, verbatim, followed by its answer and the new
    # user message.
    def encode(value):
        return json.dumps(value, ensure_ascii=False).encode("utf-8")

    assert [m["role"] for m in sent[1:]] == ["user", "assistant", "tool"]
    assert encode(replayed[1:len(sent)]) == encode(sent[1:])
    assert replayed[len(sent)]["role"] == "assistant"
    assert replayed[len(sent)]["content"] == "Answer 2."
    assert replayed[-1]["role"] == "user" and replayed[-1]["content"].endswith("And again")
    assert len(replayed) == len(sent) + 2
    assert encode(turn_two_first["tools"]) == encode(turn_one_last["tools"])


@pytest.mark.parametrize("source", ["question", "queue", "direct"])
def test_only_direct_turn_prompt_can_seed_instrument_identity(tmp_path, monkeypatch, source):
    market_calls = []
    factory, _ = _market_registry(market_calls, monkeypatch)

    def policy(llm, messages, tools, on_text):
        if len(llm.requests) == 1:
            return _response(calls=(_call("quote", "get_market_data", codes=["NVDA.US"]),))
        return _response(content="done")

    service = _service(tmp_path, monkeypatch, factory, _PolicyLLM(policy))
    session = service.create_session(title="input provenance")
    sid = session.session_id
    log = service.store.thread_log(sid)
    if source == "question":
        log.append("question", "prior", question_id="q1", prompt="Choose a comparison",
                   options=["NVDA.US", "AAPL.US"], allow_free_text=True)

    async def scenario():
        if source == "queue":
            service.pending_inputs.add(sid, "NVDA.US", queued_during="prior", include_shell_tools=False)
            service._start_next_input(sid)
            await service._active_tasks[sid]
        else:
            await _send(service, sid, "NVDA.US")

    asyncio.run(scenario())
    items = log.read()
    user = next(item for item in items if item.type == "user")
    assert user.get("content") == "NVDA.US"
    if source == "question":
        assert user.get("answer_to_question_id") == "q1"
    result = next(item for item in items if item.get("tool_call_id") == "quote")
    if source == "direct":
        assert result.get("status") == "ok" and len(market_calls) == 1
    else:
        assert json.loads(result.get("content")).get("error_code") == "identity_required"
        assert market_calls == []


@pytest.mark.parametrize("stage", ["registry", "stream"])
def test_failed_attempt_scrubs_exception_before_persistence_and_display(tmp_path, monkeypatch, stage):
    def fail(*_args, **_kwargs):
        raise RuntimeError("offline failure: api_key=private-error-detail")

    llm = _PolicyLLM(fail)
    service = _service(tmp_path, monkeypatch, fail if stage == "registry" else ToolRegistry, llm)
    sid = service.create_session(title="error projection").session_id
    turn = asyncio.run(_send(service, sid, "Inspect the failure"))
    attempt = service.store.get_attempt(sid, turn)

    assert attempt.error == "offline failure: api_key=[redacted]"
    assert "private-error-detail" not in service.store.thread_log(sid).path.read_text()
    assert "private-error-detail" not in str(service.get_messages(sid))
    if attempt.run_dir:
        assert "private-error-detail" not in (Path(attempt.run_dir) / "state.json").read_text()


@pytest.mark.parametrize("first_response", ["text", "tool", "none"])
def test_kernel_dispatch_reaches_provider_thread_and_sse(tmp_path, monkeypatch, first_response):
    from src.kernel.contracts import LLMResponse, ToolCallRequest

    def respond(llm, messages, tools, on_text):
        if first_response == "none" and len(llm.requests) == 1:
            return None
        if first_response == "tool" and len(llm.requests) == 1:
            return LLMResponse(tool_calls=[ToolCallRequest("quote", "lookup", {"key": "us"})])
        if first_response == "tool":
            assert [m["tool_call_id"] for m in _tool_messages(messages, "lookup")] == ["quote"]
        on_text("Delivered.")
        return LLMResponse(content="Delivered.")

    llm = _PolicyLLM(respond)
    service = _service(tmp_path, monkeypatch, _lookup_factory(), llm)

    async def scenario():
        sid = service.create_session("kernel dispatch").session_id
        turn = await _send(service, sid, "Inspect the fixture")
        items = _turn_items(service, sid, turn)
        assert items[-1].type == "turn_end" and items[-1].get("status") == "completed"
        stream = service.thread_events.stream(sid, cursor=0)
        frames = []
        try:
            async for event in stream:
                fields = dict(line.split(": ", 1) for line in event.to_sse().splitlines() if line)
                frames.append((fields["event"], json.loads(fields["data"])))
                if fields["event"] == "run.completed":
                    break
        finally:
            await stream.aclose()
        completed = [data["item"] for kind, data in frames if kind == "item.completed"]
        answers = [row["content"] for row in completed if row["type"] == "assistant" and row["phase"] == "final"]
        tool_results = [row["tool_call_id"] for row in completed if row["type"] == "tool_result"]
        assert answers == ["Delivered."]
        assert tool_results == (["quote"] if first_response == "tool" else [])

    asyncio.run(asyncio.wait_for(scenario(), timeout=15))
    assert len(llm.requests) == (1 if first_response == "text" else 2)
