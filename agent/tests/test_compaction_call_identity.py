"""Compaction may recover lost readonly results, never replay side effects."""

from __future__ import annotations

import json
from itertools import count
from types import SimpleNamespace

import pytest

from src.agent.context import ContextBuilder
from src.agent.loop import (
    AgentLoop,
    COLLAPSE_TEXT_MIN,
    KEEP_RECENT,
    _STUB_RESULT_CONTENT,
    _context_collapse,
    _fix_tool_pairs,
    _is_cleared,
)
from src.agent.tools import BaseTool, ToolRegistry
from src.agent.trace import TraceWriter


class _Query(BaseTool):
    name = "get_financial_statements"
    repeatable = False
    is_readonly = True

    def __init__(self):
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps({"status": "ok", "rows": ["x" * 200]})


@pytest.fixture
def harness(tmp_path):
    tool = _Query()
    registry = ToolRegistry()
    registry.register(tool)
    agent = AgentLoop(
        registry=registry,
        llm=SimpleNamespace(chat=lambda *a, **kw: SimpleNamespace(content="summary")),
    )
    agent.memory.run_dir = str(tmp_path)
    trace = TraceWriter(tmp_path)
    messages = [{"role": "system", "content": "system"}]
    react = []
    call_ids = count()

    def call(arguments, name=None):
        call_id = f"call_{next(call_ids)}"
        name = name or tool.name
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
            }
        )
        agent._process_tool_calls(
            [SimpleNamespace(id=call_id, name=name, arguments=arguments)],
            ContextBuilder,
            messages,
            trace,
            react,
            1,
        )
        return messages[-1]

    def pad(count=KEEP_RECENT):
        for i in range(count):
            call({"padding": i}, name="padding_tool")

    yield SimpleNamespace(
        tool=tool,
        agent=agent,
        trace=trace,
        messages=messages,
        call=call,
        pad=pad,
        run_dir=tmp_path,
    )
    trace.close()


def test_microcompact_reopens_only_lost_argument_variant(harness):
    h = harness
    income = h.call({"statement": "income"})
    balance = h.call({"statement": "balance"})
    h.pad(KEEP_RECENT - 1)

    h.agent._microcompact_and_unblock(h.messages, h.trace, 2)

    assert _is_cleared(income["content"])
    assert not _is_cleared(balance["content"])
    result = h.call({"statement": "income"})
    assert json.loads(result["content"])["status"] == "ok"
    assert len(h.tool.calls) == 2, "lost income must replay without another external query"
    result = h.call({"statement": "balance"})
    assert json.loads(result["content"])["skipped"] is True
    assert len(h.tool.calls) == 2, "readable balance must remain gated"


def test_variants_clear_separately_and_second_pass_is_idempotent(harness):
    h = harness
    income_args = {"statement": "income", "large": "a" * (COLLAPSE_TEXT_MIN + 1)}
    h.call(income_args)
    income_call = h.messages[1]["tool_calls"][0]
    h.call({"statement": "balance"})
    h.pad(KEEP_RECENT - 1)
    assert h.agent._microcompact_and_unblock(h.messages, h.trace, 2) == [h.tool.name]
    assert h.agent._microcompact_and_unblock(h.messages, h.trace, 3) == []
    h.pad(1)
    assert h.agent._microcompact_and_unblock(h.messages, h.trace, 4) == [h.tool.name]
    assert h.agent._microcompact_and_unblock(h.messages, h.trace, 5) == []

    _context_collapse(h.messages)
    assert income_call["function"]["arguments"] == "{}"
    # Layer 2's lossy arguments must not change the captured identity.
    h.agent._auto_compact(h.messages, h.run_dir, h.trace)
    assert json.loads(h.call(income_args)["content"])["status"] == "ok"
    assert json.loads(h.call({"statement": "balance"})["content"])["status"] == "ok"
    assert len(h.tool.calls) == 2, "both compacted readonly variants must replay from run cache"
    assert json.loads(h.call(income_args)["content"])["skipped"] is True
    assert len(h.tool.calls) == 2


@pytest.mark.parametrize("compact", ["micro", "auto"])
@pytest.mark.parametrize("duplicate", ["success", "skipped", "error", "stub"])
def test_only_real_readable_duplicate_keeps_lock(
    harness, monkeypatch, compact, duplicate
):
    h = harness
    args = {"statement": "income"}
    original = h.call(args)
    if duplicate != "skipped":
        h.tool.repeatable = True
    if duplicate == "error":
        monkeypatch.setattr(h.tool, "execute", lambda **kw: '{"status":"error"}')
    second = h.call(args)
    h.tool.repeatable = False
    if duplicate == "error":
        monkeypatch.undo()
    if duplicate == "stub":
        h.messages.remove(second)
        _fix_tool_pairs(h.messages)
        second = h.messages[-1]
        assert second["content"] == _STUB_RESULT_CONTENT
    calls_before = len(h.tool.calls)
    if compact == "micro":
        h.pad(KEEP_RECENT - 1)
        h.agent._microcompact_and_unblock(h.messages, h.trace, 2)
        assert _is_cleared(original["content"])
    else:
        h.agent._auto_compact(h.messages, h.run_dir, h.trace)
        assert original not in h.messages
    assert second in h.messages
    result = h.call(args)
    if duplicate == "success":
        assert json.loads(result["content"])["skipped"] is True
    else:
        assert json.loads(result["content"])["status"] == "ok"
    assert len(h.tool.calls) == calls_before, (
        "a lost successful readonly observation must replay even when the visible duplicate is skipped, failed, or stubbed"
    )


@pytest.mark.parametrize("compact", ["micro", "auto"])
def test_compaction_never_replays_mutating_tool(harness, compact):
    h = harness
    h.tool.name = "place_order"
    h.tool.is_readonly = False
    h.agent.registry.register(h.tool)
    args = {"symbol": "TEST", "quantity": 1}
    original = h.call(args)
    h.pad()
    if compact == "micro":
        assert h.agent._microcompact_and_unblock(h.messages, h.trace, 2) == []
        assert _is_cleared(original["content"])
    else:
        h.agent._auto_compact(h.messages, h.run_dir, h.trace)
        assert original not in h.messages
    result = h.call(args)
    assert json.loads(result["content"])["skipped"] is True
    assert len(h.tool.calls) == 1, "losing context must never replay an order"


def test_compaction_uses_same_run_dir_identity_as_gate(harness):
    h = harness
    h.call({"statement": "income"})
    h.pad()
    h.agent._microcompact_and_unblock(h.messages, h.trace, 2)
    result = h.call({"run_dir": ".", "statement": "income"})
    assert json.loads(result["content"])["status"] == "ok"
    assert len(h.tool.calls) == 1, "normalized run_dir identity must replay rather than refetch"
    result = h.call({"statement": "income", "run_dir": str(h.run_dir)})
    assert json.loads(result["content"])["skipped"] is True
    assert len(h.tool.calls) == 1


def test_none_canonical_key_never_creates_lock(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(h.agent, "_identical_call_key", lambda *args: None)
    h.call({"statement": "income"})
    h.pad()
    h.agent._microcompact_and_unblock(h.messages, h.trace, 2)
    h.agent._auto_compact(h.messages, h.run_dir, h.trace)
    h.call({"statement": "income"})
    h.call({"statement": "income"})
    assert len(h.tool.calls) == 3
    assert not h.agent._called_ok
    assert not h.agent._successful_call_keys


def test_recovered_cached_result_restores_identical_call_gate(harness):
    h = harness
    h.tool.deterministic = True
    args = {"statement": "income"}
    h.call(args)
    h.pad()
    h.agent._microcompact_and_unblock(h.messages, h.trace, 2)
    assert json.loads(h.call(args)["content"])["status"] == "ok"
    assert len(h.tool.calls) == 1, "recovery must use the deterministic cache"
    assert json.loads(h.call(args)["content"]).get("skipped") is True
    assert len(h.tool.calls) == 1


def test_replayable_repeatable_result_restores_gate_after_one_replay(harness):
    """Match deterministic recovery semantics for mutable readonly replay.

    One genuine context loss permits one run-scoped replay. Once that payload
    is visible again, an immediate identical planner request is skipped rather
    than replayed again or re-fetched. A later genuine context loss may reopen
    the same exact identity once more.
    """
    h = harness
    h.tool.repeatable = True
    h.tool.replay_after_compaction = True
    args = {"statement": "income"}

    first = h.call(args)
    assert len(h.tool.calls) == 1

    h.pad()
    h.agent._microcompact_and_unblock(h.messages, h.trace, 2)
    assert _is_cleared(first["content"])

    replay = h.call(args)
    assert json.loads(replay["content"])["status"] == "ok"
    assert len(h.tool.calls) == 1, "lost readonly data must replay without refetch"

    repeated = h.call(args)
    repeated_payload = json.loads(repeated["content"])
    assert repeated_payload.get("skipped") is True
    assert "restored from the run-scoped replay cache" in repeated_payload["reason"]
    assert len(h.tool.calls) == 1, "visible replay must restore the exact-call gate"

    # Lose the restored copy in a later compaction: that is a new recovery
    # event, so one more replay is allowed, still without an external fetch.
    h.pad()
    h.agent._microcompact_and_unblock(h.messages, h.trace, 3)
    second_replay = h.call(args)
    assert json.loads(second_replay["content"])["status"] == "ok"
    assert len(h.tool.calls) == 1


def test_readable_cached_duplicate_keeps_exact_key_locked(harness):
    h = harness
    # A repeatable deterministic tool can have two successful readable copies,
    # including one served by the cache, before the gate becomes applicable.
    h.tool.repeatable = True
    h.tool.deterministic = True
    original = h.call({"statement": "income"})
    cached = h.call({"statement": "income"})
    h.tool.repeatable = False
    h.pad(KEEP_RECENT - 1)

    reopened = h.agent._microcompact_and_unblock(h.messages, h.trace, 2)

    assert _is_cleared(original["content"])
    assert not _is_cleared(cached["content"])
    assert h.tool.name not in reopened
    result = h.call({"statement": "income"})
    assert json.loads(result["content"])["skipped"] is True
    assert len(h.tool.calls) == 1


@pytest.mark.parametrize("degraded", [False, True])
def test_auto_compact_reopens_head_but_preserves_tail_gate(
    harness, monkeypatch, degraded
):
    h = harness
    h.call({"statement": "income"})
    balance = h.call({"statement": "balance"})
    # All messages fit: the real fallback split folds the income pair and
    # retains the balance pair, without mocking the tail selector.
    if degraded:

        def fail_summary(*args, **kwargs):
            raise RuntimeError("offline summary failure")

        monkeypatch.setattr(h.agent.llm, "chat", fail_summary)
    monkeypatch.setattr("src.agent.loop._llm_timeout_seconds", lambda: 1)

    h.agent._auto_compact(h.messages, h.run_dir, h.trace)

    assert balance in h.messages
    if degraded:
        assert "compaction degraded" in h.messages[1]["content"]
    assert json.loads(h.call({"statement": "income"})["content"])["status"] == "ok"
    assert len(h.tool.calls) == 2, "summary is not original income data; replay must restore it"
    result = h.call({"statement": "balance"})
    assert json.loads(result["content"])["skipped"] is True
    assert len(h.tool.calls) == 2


def test_auto_compact_summary_call_sees_the_bound_llm_session(harness, monkeypatch):
    """The compaction thread inherits the run's session binding (#1416).

    ``AgentLoop.run()`` binds the session id in a ``ContextVar``. A fresh
    thread starts with an empty context, so the summary call used to go out
    unbound and OpenCode Go saw a second conversation id for the same session.
    """
    from src.providers.session_context import (
        bind_llm_session_id,
        current_llm_session_id,
        reset_llm_session_id,
    )

    h = harness
    h.call({"statement": "income"})
    h.call({"statement": "balance"})
    seen: list[str] = []

    def chat(*args, **kwargs):
        seen.append(current_llm_session_id())
        return SimpleNamespace(content="summary")

    monkeypatch.setattr(h.agent.llm, "chat", chat)
    monkeypatch.setattr("src.agent.loop._llm_timeout_seconds", lambda: 1)
    token = bind_llm_session_id("vibe-session-42")
    try:
        h.agent._auto_compact(h.messages, h.run_dir, h.trace)
    finally:
        reset_llm_session_id(token)

    assert seen, "the compaction made no summary call"
    assert seen == ["vibe-session-42"] * len(seen)
