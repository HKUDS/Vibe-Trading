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
    assert key not in loop._readonly_replay_protected

    # First exact call after loss is restored from the run-scoped cache, and
    # only a restored key is protected against an immediate re-fetch.
    tc3 = SimpleNamespace(name="read_url", arguments=args, id="call-3")
    loop._process_tool_calls([tc3], _Context(), messages, trace, react_trace, 3)
    assert registry.execute_calls == 2
    assert key not in loop._readonly_replay_ready
    assert key in loop._readonly_replay_protected

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


def test_past_the_replay_budget_a_lost_call_runs_again() -> None:
    """The budget bounds replay, not access to evidence: once it is spent, a
    lost call runs again as it does without replay, instead of being refused
    with "use the previous result" for a payload the model cannot see."""
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

    assert reopened == ["read_url"]
    assert key not in loop._called_ok
    assert key not in loop._readonly_replay_protected

    messages = []
    trace = _Trace()
    tc = SimpleNamespace(name="read_url", arguments=args, id="budget-exhausted")
    loop._process_tool_calls([tc], _Context(), messages, trace, [], 9)

    assert registry.execute_calls == 1
    assert "skipped" not in messages[-1]["content"]
    assert not any(e["type"] == "tool_result_replayed" for e in trace.events)
    assert key not in loop._readonly_replay_ready


def test_a_first_loss_after_the_budget_is_spent_elsewhere_runs_again() -> None:
    """A non-repeatable call lost for the first time, after other calls used
    the budget, used to stay in the success set and come back as "already
    completed successfully. Use the previous result." (#1488 review)."""
    registry = _Registry()
    loop = _loop(registry)
    args = {"symbol": "600519.SH"}
    loop._process_tool_calls([SimpleNamespace(name="get_stock_news", arguments=args, id="n1")], _Context(), [], _Trace(), [], 1)
    key = loop._identical_call_key("get_stock_news", args)
    loop._readonly_replay_recoveries = MAX_READONLY_REPLAY_RECOVERIES

    assert loop._unblock_lost_readonly_results([], {key}) == ["get_stock_news"]
    messages = []
    loop._process_tool_calls([SimpleNamespace(name="get_stock_news", arguments=args, id="n2")], _Context(), messages, _Trace(), [], 2)

    assert registry.execute_calls == 2
    assert "skipped" not in messages[-1]["content"]


def test_one_compaction_cannot_replay_past_the_budget() -> None:
    """The cap is checked when a call is restored, not when keys are reopened:
    with one recovery left, four lost keys give one replay and three re-runs."""
    registry = _Registry()
    loop = _loop(registry)
    calls = [{"symbol": f"S{i}"} for i in range(4)]
    for i, args in enumerate(calls):
        loop._process_tool_calls([SimpleNamespace(name="get_stock_news", arguments=args, id=f"s{i}")], _Context(), [], _Trace(), [], 1)
    loop._readonly_replay_recoveries = MAX_READONLY_REPLAY_RECOVERIES - 1
    loop._unblock_lost_readonly_results([], {loop._identical_call_key("get_stock_news", a) for a in calls})

    trace = _Trace()
    for i, args in enumerate(calls):
        loop._process_tool_calls([SimpleNamespace(name="get_stock_news", arguments=args, id=f"r{i}")], _Context(), [], trace, [], 2)

    assert sum(e["type"] == "tool_result_replayed" for e in trace.events) == 1
    assert registry.execute_calls == 4 + 3
    assert loop._readonly_replay_recoveries == MAX_READONLY_REPLAY_RECOVERIES


class _ReadAndWriteRegistry:
    """factor_analysis reads a file that a bash call rewrites."""

    def __init__(self):
        self.version = "v1"
        self.execute_calls = 0

    def get(self, name):
        return SimpleNamespace(
            is_readonly=name != "bash", repeatable=False, deterministic=False, replay_after_compaction=False
        )

    def execute(self, name, args):
        self.execute_calls += 1
        if name == "bash":
            self.version = "v2"
            return '{"status":"ok"}'
        return '{"status":"ok","version":"%s"}' % self.version


def test_a_write_makes_earlier_readonly_results_unreplayable() -> None:
    """A result cached before a write may describe a file the write changed:
    after the write, a lost call runs again and reads the new file."""
    registry = _ReadAndWriteRegistry()
    loop = _loop(registry)
    read = {"factor_csv": "factor.csv"}
    loop._process_tool_calls([SimpleNamespace(name="factor_analysis", arguments=read, id="f1")], _Context(), [], _Trace(), [], 1)
    loop._process_tool_calls(
        [SimpleNamespace(name="bash", arguments={"command": "python make_factor.py > factor.csv"}, id="w1")],
        _Context(), [], _Trace(), [], 2,
    )
    key = loop._identical_call_key("factor_analysis", read)
    loop._unblock_lost_readonly_results([], {key})

    messages = []
    loop._process_tool_calls([SimpleNamespace(name="factor_analysis", arguments=read, id="f2")], _Context(), messages, _Trace(), [], 3)

    assert '"version":"v2"' in messages[-1]["content"]
    assert "_vibe_replay" not in messages[-1]["content"]


def test_without_a_write_the_lost_result_is_restored() -> None:
    """The other side of the write rule: nothing written, so no re-run."""
    registry = _ReadAndWriteRegistry()
    loop = _loop(registry)
    read = {"factor_csv": "factor.csv"}
    loop._process_tool_calls([SimpleNamespace(name="factor_analysis", arguments=read, id="f1")], _Context(), [], _Trace(), [], 1)
    loop._unblock_lost_readonly_results([], {loop._identical_call_key("factor_analysis", read)})

    messages = []
    loop._process_tool_calls([SimpleNamespace(name="factor_analysis", arguments=read, id="f2")], _Context(), messages, _Trace(), [], 2)

    assert registry.execute_calls == 1
    assert "_vibe_replay" in messages[-1]["content"]
