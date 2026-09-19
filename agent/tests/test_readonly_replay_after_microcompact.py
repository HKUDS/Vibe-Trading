from __future__ import annotations

import threading
from types import SimpleNamespace

from src.agent.loop import AgentLoop, MAX_READONLY_REPLAY_RECOVERIES
from src.agent.tool_progress import NO_PROGRESS_LIMIT, ToolProgress
from src.tools.web_reader_tool import WebReaderTool


class _Registry:
    def __init__(
        self,
        *,
        readonly=True,
        repeatable=False,
        deterministic=False,
        replay_after_compaction=False,
    ):
        self.tool = SimpleNamespace(
            is_readonly=readonly,
            repeatable=repeatable,
            deterministic=deterministic,
            replay_after_compaction=replay_after_compaction,
        )
        self.execute_calls = 0

    def get(self, name):
        return self.tool

    def execute(self, name, args):
        self.execute_calls += 1
        return '{"status":"ok","value":"fresh"}'


class _Context:
    @staticmethod
    def format_tool_result(call_id, name, result):
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": result,
        }


class _Trace:
    def __init__(self):
        self.events = []

    def write(self, event):
        self.events.append(event)

    def write_tool_result(
        self, *, call_id, result, tool_name, status, elapsed_ms, iteration
    ):
        self.events.append(
            {
                "type": "tool_result",
                "call_id": call_id,
                "result": result,
                "tool": tool_name,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "iter": iteration,
            }
        )


def _loop(registry=None):
    loop = object.__new__(AgentLoop)
    loop.registry = registry or _Registry()
    loop.memory = SimpleNamespace(
        run_dir="/tmp/test-run",
        increment=lambda *_args, **_kwargs: None,
    )
    loop._called_ok = set()
    loop._successful_call_keys = {}
    loop._called_identical = {}
    loop._readonly_replay_cache = {}
    loop._readonly_replay_ready = set()
    loop._readonly_replay_protected = set()
    loop._readonly_replay_recoveries = 0
    loop._grounding = None
    loop._cancel_event = threading.Event()
    loop._event_callback = None
    loop._tool_progress = ToolProgress()
    return loop


def test_compaction_marks_lost_readonly_result_for_run_scoped_replay():
    loop = _loop()
    key = loop._identical_call_key("read_url", {"url": "https://example.test/report"})
    assert key is not None
    loop._called_ok.add(key)
    loop._readonly_replay_cache[key] = '{"status":"ok","body":"report"}'
    reopened = loop._unblock_lost_readonly_results([], {key})
    assert reopened == ["read_url"]
    assert key not in loop._called_ok
    assert key in loop._readonly_replay_ready
    assert key not in loop._readonly_replay_protected


def test_replay_restores_result_without_external_execution():
    registry = _Registry()
    loop = _loop(registry)
    args = {"url": "https://example.test/report"}
    key = loop._identical_call_key("read_url", args)
    assert key is not None
    cached = '{"status":"ok","body":"report"}'
    loop._readonly_replay_cache[key] = cached
    loop._readonly_replay_ready.add(key)
    loop._readonly_replay_protected.add(key)
    tc = SimpleNamespace(name="read_url", arguments=args, id="replay-1")
    messages = []
    trace = _Trace()
    react_trace = []
    loop._process_tool_calls([tc], _Context(), messages, trace, react_trace, 22)
    assert registry.execute_calls == 0
    replayed_payload = __import__("json").loads(messages[-1]["content"])
    assert replayed_payload["status"] == "ok"
    assert replayed_payload["body"] == "report"
    assert replayed_payload["_vibe_replay"]["restored"] is True
    assert "continue the analysis" in replayed_payload["_vibe_replay"]["notice"]
    assert "freshness arguments" in replayed_payload["_vibe_replay"]["notice"]
    assert key in loop._called_ok
    assert key not in loop._readonly_replay_ready
    assert key in loop._readonly_replay_protected
    assert trace.events[-1]["type"] == "tool_result_replayed"
    assert loop._tool_progress.finish_iteration() is False
    assert loop._tool_progress.stalled_iterations == 0


def test_repeatable_requires_explicit_compaction_replay_opt_in():
    loop = _loop(_Registry())
    ordinary_repeatable = _Registry(repeatable=True).get("poll")
    assert loop._readonly_replay_allowed(ordinary_repeatable, {}) is False

    replayable_repeatable = _Registry(
        repeatable=True,
        replay_after_compaction=True,
    ).get("read_url")
    assert loop._readonly_replay_allowed(replayable_repeatable, {"url": "x"}) is True


def test_no_cache_bypasses_repeatable_compaction_replay():
    loop = _loop(_Registry())
    replayable_repeatable = _Registry(
        repeatable=True,
        replay_after_compaction=True,
    ).get("read_url")
    assert (
        loop._readonly_replay_allowed(
            replayable_repeatable,
            {"url": "x", "no_cache": True},
        )
        is False
    )


def test_repeatable_opt_in_runs_normally_before_compaction_then_stays_replay_protected():
    registry = _Registry(repeatable=True, replay_after_compaction=True)
    loop = _loop(registry)
    args = {"url": "https://example.test/report"}
    messages = []
    trace = _Trace()
    react_trace = []

    tc1 = SimpleNamespace(name="read_url", arguments=args, id="call-1")
    loop._process_tool_calls([tc1], _Context(), messages, trace, react_trace, 1)
    assert registry.execute_calls == 1

    # Before compaction loss, repeatable keeps its ordinary refresh semantics.
    tc2 = SimpleNamespace(name="read_url", arguments=args, id="call-2")
    loop._process_tool_calls([tc2], _Context(), messages, trace, react_trace, 2)
    assert registry.execute_calls == 2

    key = loop._identical_call_key("read_url", args)
    assert key is not None
    reopened = loop._unblock_lost_readonly_results([], {key})
    assert reopened == ["read_url"]
    assert key in loop._readonly_replay_ready
    assert key in loop._readonly_replay_protected

    # First exact call after loss is restored from the run-scoped cache.
    tc3 = SimpleNamespace(name="read_url", arguments=args, id="call-3")
    loop._process_tool_calls([tc3], _Context(), messages, trace, react_trace, 3)
    assert registry.execute_calls == 2
    assert key not in loop._readonly_replay_ready

    # An immediate identical repeat must not escape to the external source or
    # replay the same payload again just because the tool is repeatable. The
    # restored result is already visible, so the exact-call protection gate
    # returns a synthetic skip and tells the planner to continue with it.
    tc4 = SimpleNamespace(name="read_url", arguments=args, id="call-4")
    loop._process_tool_calls([tc4], _Context(), messages, trace, react_trace, 4)
    assert registry.execute_calls == 2
    assert sum(e["type"] == "tool_result_replayed" for e in trace.events) == 1
    assert messages[-1]["content"]
    assert '"skipped": true' in messages[-1]["content"]
    assert "restored from the run-scoped replay cache" in messages[-1]["content"]

    # If compaction removes the replay again, the same key can be restored once
    # more without a network fetch.
    loop._unblock_lost_readonly_results([], {key})
    tc5 = SimpleNamespace(name="read_url", arguments=args, id="call-5")
    loop._process_tool_calls([tc5], _Context(), messages, trace, react_trace, 5)
    assert registry.execute_calls == 2
    assert sum(e["type"] == "tool_result_replayed" for e in trace.events) == 2


def test_no_cache_executes_externally_even_after_normal_read_is_protected():
    registry = _Registry(repeatable=True, replay_after_compaction=True)
    loop = _loop(registry)
    normal_args = {"url": "https://example.test/report"}
    normal_key = loop._identical_call_key("read_url", normal_args)
    assert normal_key is not None
    loop._readonly_replay_cache[normal_key] = '{"status":"ok","body":"cached"}'
    loop._readonly_replay_protected.add(normal_key)

    fresh_args = {"url": "https://example.test/report", "no_cache": True}
    tc = SimpleNamespace(name="read_url", arguments=fresh_args, id="fresh-1")
    loop._process_tool_calls([tc], _Context(), [], _Trace(), [], 6)
    assert registry.execute_calls == 1


def test_different_repeatable_arguments_still_execute_externally_after_protection():
    registry = _Registry(repeatable=True, replay_after_compaction=True)
    loop = _loop(registry)
    protected_args = {"url": "https://example.test/a"}
    protected_key = loop._identical_call_key("read_url", protected_args)
    assert protected_key is not None
    loop._readonly_replay_cache[protected_key] = '{"status":"ok","body":"a"}'
    loop._readonly_replay_protected.add(protected_key)

    tc = SimpleNamespace(
        name="read_url",
        arguments={"url": "https://example.test/b"},
        id="different-1",
    )
    loop._process_tool_calls([tc], _Context(), [], _Trace(), [], 7)
    assert registry.execute_calls == 1


def test_web_reader_declares_repeatable_compaction_replay_contract():
    tool = WebReaderTool()
    assert tool.is_readonly is True
    assert tool.repeatable is True
    assert tool.replay_after_compaction is True
    assert tool.deterministic is False


def test_mutating_tools_and_existing_deterministic_cache_stay_separate():
    loop = _loop(_Registry(readonly=False))
    assert loop._readonly_replay_allowed(loop.registry.get("write_file"), {}) is False
    deterministic = _Registry(deterministic=True).get("financial_rigor")
    assert loop._readonly_replay_allowed(deterministic, {}) is False


def test_replay_only_iterations_remain_bounded_by_no_progress_limit():
    progress = ToolProgress()
    for iteration in range(NO_PROGRESS_LIMIT + 1):
        progress.mark_context_restored()
        stopped = progress.finish_iteration()
        if stopped:
            break
    assert stopped is True
    assert progress.stalled_iterations == NO_PROGRESS_LIMIT
    assert iteration <= NO_PROGRESS_LIMIT


def test_run_scoped_replay_recovery_budget_keeps_lost_calls_locked() -> None:
    registry = _Registry(repeatable=True, replay_after_compaction=True)
    loop = _loop(registry)
    args = {"url": "https://example.test/report"}
    key = loop._identical_call_key("read_url", args)
    assert key is not None
    loop._called_ok.add(key)
    loop._readonly_replay_cache[key] = '{"status":"ok","body":"report"}'
    loop._readonly_replay_protected.add(key)
    loop._readonly_replay_recoveries = MAX_READONLY_REPLAY_RECOVERIES

    reopened = loop._unblock_lost_readonly_results([], {key})

    assert reopened == []
    assert key in loop._called_ok
    assert key not in loop._readonly_replay_ready

    messages = []
    trace = _Trace()
    tc = SimpleNamespace(name="read_url", arguments=args, id="budget-exhausted")
    loop._process_tool_calls([tc], _Context(), messages, trace, [], 9)

    assert registry.execute_calls == 0
    payload = __import__("json").loads(messages[-1]["content"])
    assert payload["skipped"] is True
    assert "restored from the run-scoped replay cache" in payload["reason"]
    assert not any(e["type"] == "tool_result_replayed" for e in trace.events)
