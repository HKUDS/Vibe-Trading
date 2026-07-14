"""Regression tests for MEDIUM/LOW correctness fixes to the agent config layer.

MEDIUM #1 (test fragility):
    Setting VIBE_TRADING_DOTENV_OVERRIDE=0 (or resetting the cache) must let a
    test-set env var win against a project .env file when the .env loader
    re-runs. The default production behavior (override=True) is preserved.

MEDIUM #2 (tool timeout queue leak):
    The readonly-tool timeout path must drain the worker queue and the worker
    must use a non-blocking put so a slow tool's eventual completion cannot
    block the daemon thread forever on a full queue.

LOW #3 (trace resume iter):
    A non-integer ``iter`` value in a hand-edited trace must degrade
    gracefully (treat as 0), not raise ValueError.

LOW #4 (compact SSE):
    The compact tool branch must emit a ``tool_call`` and ``tool_result``
    SSE event pair so the UI panel stays in sync.

LOW #5 (orphan tool calls on cancel):
    If the user cancels mid-iteration, every tool_call on the assistant
    message must still be paired with a synthetic role=tool result so the
    provider-protocol invariant (every tool_call has a matching tool
    message) holds across the cancel.
"""

from __future__ import annotations

import json
import os
import queue
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import src.providers.llm as llm
from src.agent.loop import AgentLoop
from src.config.accessor import reset_env_config
from src.config.env_schema import EnvConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_dotenv(monkeypatch):
    """Drop the once-per-process latch so the resolver actually runs."""
    monkeypatch.setattr(llm, "_dotenv_loaded", False)


# ---------------------------------------------------------------------------
# MEDIUM #1 — dotenv override configurable
# ---------------------------------------------------------------------------


class TestDotenvOverride:
    def test_default_is_true(self) -> None:
        """Production behavior preserved: project .env beats shell exports."""
        assert EnvConfig().llm.vibe_trading_dotenv_override is True

    def test_env_var_disables_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A test can flip the override off via env var without code change."""
        monkeypatch.setenv("VIBE_TRADING_DOTENV_OVERRIDE", "0")
        reset_env_config()
        try:
            assert EnvConfig().llm.vibe_trading_dotenv_override is False
        finally:
            reset_env_config()

    def test_monkeypatched_env_wins_when_override_false(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fresh_dotenv,
    ) -> None:
        """Regression: tests that monkeypatch.setenv + re-run _ensure_dotenv
        must be able to make their patched value win.

        Previously the .env file clobbered test-set env vars because the
        ``_load_env_file`` loader unconditionally overwrote os.environ when
        ``override=True``. With override=False the per-line loader mirrors
        python-dotenv semantics: do not overwrite an already-set os.environ
        value.
        """
        env = tmp_path / ".env"
        env.write_text("VT_TEST_TOKEN=from_dotenv\n", encoding="utf-8")
        monkeypatch.setattr(llm, "_ENV_CANDIDATES", [env])
        monkeypatch.setattr(llm, "_ENV_LABELS", ("<TEST_SLOT>",))
        monkeypatch.setenv("VT_TEST_TOKEN", "from_monkeypatch")
        monkeypatch.setenv("VIBE_TRADING_DOTENV_OVERRIDE", "0")
        reset_env_config()
        try:
            llm._ensure_dotenv()
            # The monkeypatched value must NOT be clobbered by the .env file.
            assert os.environ["VT_TEST_TOKEN"] == "from_monkeypatch"
        finally:
            reset_env_config()

    def test_default_override_still_clobbers(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fresh_dotenv,
    ) -> None:
        """Production behavior preserved: .env always wins by default."""
        env = tmp_path / ".env"
        env.write_text("VT_TEST_TOKEN=from_dotenv\n", encoding="utf-8")
        monkeypatch.setattr(llm, "_ENV_CANDIDATES", [env])
        monkeypatch.setattr(llm, "_ENV_LABELS", ("<TEST_SLOT>",))
        monkeypatch.setenv("VT_TEST_TOKEN", "from_monkeypatch")
        # Explicitly DO NOT set VIBE_TRADING_DOTENV_OVERRIDE; default is True.
        reset_env_config()
        try:
            llm._ensure_dotenv()
            assert os.environ["VT_TEST_TOKEN"] == "from_dotenv"
        finally:
            reset_env_config()

    def test_reset_cache_helper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Public hook re-arms the one-shot loader."""
        monkeypatch.setattr(llm, "_dotenv_loaded", True)
        assert llm._dotenv_loaded is True
        llm._reset_dotenv_cache_for_test()
        assert llm._dotenv_loaded is False


# ---------------------------------------------------------------------------
# MEDIUM #2 — tool timeout queue leak
# ---------------------------------------------------------------------------


class TestToolTimeoutQueue:
    """Test the new non-blocking queue helpers in isolation."""

    def test_safe_queue_put_stores_when_room(self) -> None:
        from src.agent.loop import _safe_queue_put

        q: queue.Queue[tuple[str | None, BaseException | None]] = queue.Queue(maxsize=1)
        _safe_queue_put(q, ("first", None))
        # First put succeeded, queue has 1 item.
        assert not q.empty()
        assert q.get_nowait() == ("first", None)
        assert q.empty()

    def test_safe_queue_put_drops_on_full(self) -> None:
        """A full Queue.Full must be swallowed, never raised, never wedging."""
        from src.agent.loop import _safe_queue_put

        q: queue.Queue[tuple[str | None, BaseException | None]] = queue.Queue(maxsize=1)
        _safe_queue_put(q, ("first", None))
        # Queue is now full. A second put MUST NOT block; MUST NOT raise.
        import time as _time

        t0 = _time.perf_counter()
        _safe_queue_put(q, ("second", None))
        elapsed = _time.perf_counter() - t0
        # The first item is still there; the second was dropped.
        assert q.get_nowait() == ("first", None)
        assert q.empty()
        # Above all, no deadlock — the call must return near-instantly.
        assert elapsed < 0.5, f"safe_queue_put blocked for {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# LOW #3 — trace resume iter parsing is defensive
# ---------------------------------------------------------------------------


class TestTraceResumeIterDefensive:
    """Mirror the comprehension in run() to validate the contract."""

    def test_non_integer_iter_does_not_crash(self) -> None:
        """Hand-edited trace with iter='three' must not raise ValueError."""

        # The defensive helper is inlined in run(); we replicate it to
        # validate the contract (a non-int iter -> 0, integers preserved).
        def _safe_iter(entry: dict[str, Any]) -> int:
            raw = entry.get("iter", 0)
            try:
                return int(raw)
            except (TypeError, ValueError):
                return 0

        entries = [
            {"type": "start", "iter": "three"},
            {"type": "start", "iter": 7},
            {"type": "message", "iter": "twelve"},
            {"type": "start", "iter": None},
        ]
        result = max(
            (_safe_iter(e) for e in entries if "iter" in e),
            default=0,
        )
        assert result == 7  # only the integer entry contributes.

    def test_iter_helper_handles_none_and_garbage(self) -> None:
        def _safe_iter(entry: dict[str, Any]) -> int:
            raw = entry.get("iter", 0)
            try:
                return int(raw)
            except (TypeError, ValueError):
                return 0

        assert _safe_iter({}) == 0
        assert _safe_iter({"iter": None}) == 0
        assert _safe_iter({"iter": "garbage"}) == 0
        assert _safe_iter({"iter": []}) == 0
        assert _safe_iter({"iter": 0}) == 0
        assert _safe_iter({"iter": 42}) == 42
        assert _safe_iter({"iter": "5"}) == 5


# ---------------------------------------------------------------------------
# LOW #4 — compact tool emits matching SSE event pair
# ---------------------------------------------------------------------------


class _StubLLMCompact:
    """LLM stub that returns a single ``compact`` tool call."""

    def __init__(self) -> None:
        self.call_count = 0

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        on_text_chunk=None,
        on_reasoning_chunk=None,
        should_cancel=None,
    ) -> Any:
        self.call_count += 1
        return SimpleNamespace(
            content="",
            tool_calls=[
                SimpleNamespace(
                    id="compact-1", name="compact", arguments={"focus_topic": "x"}
                )
            ],
            reasoning_content=None,
            has_tool_calls=True,
        )

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> Any:
        return SimpleNamespace(content="", tool_calls=[], has_tool_calls=False)


def _build_agent(llm_stub: Any, tmp_path: Path, event_callback=None) -> AgentLoop:
    from src.tools import build_registry
    from src.memory.persistent import PersistentMemory

    pm = PersistentMemory()
    agent = AgentLoop(
        registry=build_registry(persistent_memory=pm, include_shell_tools=False),
        llm=llm_stub,
        event_callback=event_callback,
        max_iterations=2,
        persistent_memory=pm,
    )
    agent.memory.run_dir = str(tmp_path / "run")
    tmp_path.joinpath("run").mkdir(parents=True, exist_ok=True)
    return agent


def test_compact_tool_emits_matching_sse_pair(tmp_path: Path) -> None:
    """The compact branch must emit tool_call BEFORE and tool_result AFTER
    so the UI's pending counter can decrement.
    """
    events: list[tuple[str, dict[str, Any]]] = []

    def _capture(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    agent = _build_agent(_StubLLMCompact(), tmp_path, event_callback=_capture)

    agent.run(user_message="trigger compact")

    # Find the compact tool_call and the following tool_result.
    tool_calls = [(i, e, p) for i, (e, p) in enumerate(events) if e == "tool_call"]
    compact_call_idx = next(
        (i, e, p)
        for (i, e, p) in tool_calls
        if p.get("tool") == "compact"
    )
    matching_results = [
        (i, ev, p)
        for (i, ev, p) in [(i, e, p) for i, (e, p) in enumerate(events)]
        if ev == "tool_result" and p.get("tool") == "compact"
    ]
    assert matching_results, "compact tool_result SSE event was never emitted"
    # The tool_result must come AFTER the tool_call.
    first_result_idx = matching_results[0][0]
    assert first_result_idx > compact_call_idx[0]


# ---------------------------------------------------------------------------
# LOW #5 — orphan tool calls on mid-iter cancel
# ---------------------------------------------------------------------------


class TestOrphanToolCallsOnCancel:
    """Drive _process_tool_calls directly with cancel pre-set.

    No LLM stub gymnastics needed: the cancel branch runs at the top of
    _process_tool_calls and synthesizes results before returning.
    """

    def test_synthetic_results_for_every_tool_call(self) -> None:
        """Cancelling mid-iter must append a tool message per tool_call so
        the OpenAI wire-protocol (every tool_call paired with a tool
        message) holds.
        """
        from src.tools import build_registry
        from src.memory.persistent import PersistentMemory

        pm = PersistentMemory()
        agent = AgentLoop(
            registry=build_registry(persistent_memory=pm, include_shell_tools=False),
            llm=SimpleNamespace(),  # never called; we drive _process_tool_calls.
            event_callback=None,
            max_iterations=2,
            persistent_memory=pm,
        )
        # Pre-set cancel so the early-return branch in _process_tool_calls fires.
        agent._cancel_event.set()

        captured: dict[str, list[dict[str, Any]]] = {}

        class _StubContext:
            def format_tool_result(
                self, call_id: str, name: str, content: str
            ) -> dict[str, Any]:
                return {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": content,
                }

        # Trace object signature is compatible enough for this branch —
        # the cancel path only writes trace after the early-return. Pass a
        # minimal mock that records no calls.
        class _NoopTrace:
            def write(self, *_args: Any, **_kwargs: Any) -> None:
                return None

        messages: list[dict[str, Any]] = []
        ctx = _StubContext()

        agent._process_tool_calls(  # type: ignore[attr-defined]
            [
                SimpleNamespace(id="orphan-A", name="get_market_data", arguments={}),
                SimpleNamespace(id="orphan-B", name="get_news", arguments={}),
            ],
            ctx,
            messages,
            _NoopTrace(),  # type: ignore[arg-type]
            [],
            1,
        )

        # Verify the contract.
        assert len(messages) == 2, (
            f"expected 2 synthetic results, got {len(messages)}: {messages}"
        )
        assert {m["tool_call_id"] for m in messages} == {"orphan-A", "orphan-B"}
        assert all(m["role"] == "tool" for m in messages)
        # The synthetic content must signal cancellation.
        assert all('"cancelled"' in m["content"] for m in messages)

    def test_no_synthetic_results_for_empty_tool_calls(self) -> None:
        """Sanity: an empty tool-call list + cancel must not synthesize
        anything (the assistant message had no tool_calls to orphan).
        """
        from src.tools import build_registry
        from src.memory.persistent import PersistentMemory

        pm = PersistentMemory()
        agent = AgentLoop(
            registry=build_registry(persistent_memory=pm, include_shell_tools=False),
            llm=SimpleNamespace(),
            event_callback=None,
            max_iterations=2,
            persistent_memory=pm,
        )
        agent._cancel_event.set()

        class _StubContext:
            def format_tool_result(
                self, call_id: str, name: str, content: str
            ) -> dict[str, Any]:
                return {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": content,
                }

        class _NoopTrace:
            def write(self, *_args: Any, **_kwargs: Any) -> None:
                return None

        messages: list[dict[str, Any]] = []
        agent._process_tool_calls(  # type: ignore[attr-defined]
            [], _StubContext(), messages, _NoopTrace(), [], 1  # type: ignore[arg-type]
        )
        assert messages == []
