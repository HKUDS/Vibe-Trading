"""Tests for escalating stream-retry delays and Retry-After honoring.

Issue #1208: both LLM stream-retry sites (``AgentLoop.run`` and the swarm
worker) used a constant one-shot delay, so a sustained provider outage burned
the patience budget in seconds. The delay now escalates across consecutive
retryable failures (capped exponential) and honors the provider's
``Retry-After`` header on 429/529, bounded by the configured maximum.
"""

from __future__ import annotations

import types
from pathlib import Path
from time import perf_counter as _perf
from typing import Any, Callable
from unittest.mock import patch

import pytest
from pydantic import ValidationError

import src.agent.loop as loop_mod
import src.swarm.worker as worker_mod
from src.config.env_schema import AgentTuningConfig, SwarmConfig
from src.providers.chat import LLMResponse, ProviderStreamError, ToolCallRequest

# Substantive prose so _classify_deliverable accepts the tool-less worker.
FINAL_TEXT = (
    "# BTC-USDT — Short-Term View\n\n"
    "Spot 81,704.6 (2026-05-05). 7d range 77,750-82,842.\n\n"
    "**Recommendation: accumulate on dips to 79k; invalidation below 77.5k.**\n"
    "Position 3% NAV, stop 76,900, target 86,000. Funding 0.035%/8h elevated\n"
    "but not extreme; exchange reserves declining (bullish)."
)


class _EmptyRegistry:
    """Minimal stand-in for the swarm ToolRegistry (execute returns ok)."""

    def get_definitions(self) -> list[dict]:
        """Return an empty tool-definition list."""
        return []

    def execute(self, name: str, args: dict) -> str:
        """Execute nothing; return a canned tool result."""
        return "ok"

    def get(self, name: str):
        """Return no tool metadata."""
        return None


class _ScriptedWorkerLLM:
    """Scripted ChatLLM playing a per-call script of errors and responses."""

    def __init__(self, script: list) -> None:
        """Initialize the scripted stub.

        Args:
            script: One entry per ``stream_chat`` call, consumed in order:
                an Exception to raise or an ``LLMResponse`` to return. The
                last response repeats once the script is exhausted.
        """
        self._script = list(script)
        self.calls = 0

    def __call__(self, *args, **kwargs) -> "_ScriptedWorkerLLM":
        """Support ``ChatLLM(model_name=...)`` constructor-style patching."""
        return self

    def close(self) -> None:
        """No-op: the stub owns no HTTP client."""
        return None

    def stream_chat(self, messages, tools=None, on_text_chunk=None, timeout=None):
        """Play the next scripted entry, or repeat the final response."""
        self.calls += 1
        if self._script:
            outcome = self._script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return LLMResponse(content=FINAL_TEXT)


def _transient_error() -> ProviderStreamError:
    """Build a ProviderStreamError mimicking a transient mid-stream reset."""
    return ProviderStreamError(
        provider="openrouter",
        model="test-model",
        original=ConnectionResetError("connection reset by peer"),
    )


def _rate_limit_error(retry_after: str) -> ProviderStreamError:
    """Build a retryable 429-style error carrying a Retry-After header."""
    original = Exception("rate limited: too many requests")
    original.status_code = 429  # type: ignore[attr-defined]
    original.response = types.SimpleNamespace(  # type: ignore[attr-defined]
        headers={"Retry-After": retry_after}
    )
    return ProviderStreamError(provider="openrouter", model="test-model", original=original)


def _bad_request_error() -> ProviderStreamError:
    """Build a ProviderStreamError mimicking a deterministic 400 rejection."""
    original = Exception("invalid temperature: only 1 is allowed for this model")
    original.status_code = 400  # type: ignore[attr-defined]
    return ProviderStreamError(
        provider="moonshot", model="kimi-k2.6", original=original
    )


def _tool_response(idx: int) -> LLMResponse:
    """Build a tool-call response that keeps the worker loop iterating."""
    return LLMResponse(
        content="searching...",
        tool_calls=[
            ToolCallRequest(id=f"tc{idx}", name="web_search", arguments={"q": "test"})
        ],
    )


def _run_worker(
    monkeypatch,
    tmp_path: Path,
    llm: _ScriptedWorkerLLM,
    max_iterations: int = 4,
) -> tuple[Any, list[float]]:
    """Run a swarm worker against the scripted LLM, recording sleep durations.

    Args:
        monkeypatch: pytest monkeypatch fixture (patches sleep + delay knobs).
        tmp_path: Scratch run directory.
        llm: The scripted ChatLLM stub.
        max_iterations: Worker iteration budget.

    Returns:
        Tuple of ``(WorkerResult, sleeps)`` where sleeps lists every
        ``time.sleep`` duration observed inside the worker.
    """
    sleeps: list[float] = []
    monkeypatch.setattr(worker_mod.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(worker_mod, "_STREAM_RETRY_DELAY_S", 1.0)
    monkeypatch.setattr(worker_mod, "_STREAM_RETRY_MAX_DELAY_S", 8.0)
    agent_spec = worker_mod.SwarmAgentSpec(
        id="analyst",
        role="Synthesis analyst",
        system_prompt="You synthesize upstream findings.",
        tools=[],
        skills=[],
        max_iterations=max_iterations,
        timeout_seconds=60,
    )
    task = worker_mod.SwarmTask(id="t1", agent_id="analyst", prompt_template="Summarize.")
    with (
        patch.object(worker_mod, "build_swarm_registry", lambda *a, **k: _EmptyRegistry()),
        patch.object(worker_mod, "ChatLLM", llm),
    ):
        result = worker_mod.run_worker(
            agent_spec=agent_spec,
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=tmp_path,
        )
    return result, sleeps


def test_first_failure_sleeps_configured_base(monkeypatch, tmp_path):
    """One retryable failure → exactly one sleep of the configured base (1.0)."""
    llm = _ScriptedWorkerLLM([_transient_error(), LLMResponse(content=FINAL_TEXT)])

    result, sleeps = _run_worker(monkeypatch, tmp_path, llm)

    assert result.status == "completed"
    assert sleeps == [1.0]


def test_existing_single_failure_still_retried_once(monkeypatch, tmp_path):
    """One retryable failure → exactly two stream_chat calls (no multi-retry)."""
    llm = _ScriptedWorkerLLM([_transient_error(), LLMResponse(content=FINAL_TEXT)])

    result, _ = _run_worker(monkeypatch, tmp_path, llm)

    assert result.status == "completed"
    assert llm.calls == 2


def test_delay_escalates_across_consecutive_iterations(monkeypatch, tmp_path):
    """Consecutive failing iterations escalate 1.0 → 2.0 → 4.0 despite retries.

    A successful retry must NOT reset the streak; only a clean first-attempt
    success does. Iterations 0-2 each fail and retry — the first two retries
    return tool calls so the loop continues, the final retry returns the
    final text — pinning sleeps [1.0, 2.0, 4.0].
    """
    llm = _ScriptedWorkerLLM([
        _transient_error(), _tool_response(0),
        _transient_error(), _tool_response(1),
        _transient_error(), LLMResponse(content=FINAL_TEXT),
    ])

    result, sleeps = _run_worker(monkeypatch, tmp_path, llm, max_iterations=4)

    assert result.status == "completed"
    assert sleeps == [1.0, 2.0, 4.0]


def test_streak_resets_after_clean_iteration(monkeypatch, tmp_path):
    """A clean first-attempt iteration resets the streak to the base delay."""
    llm = _ScriptedWorkerLLM([_tool_response(0), _transient_error()])

    result, sleeps = _run_worker(monkeypatch, tmp_path, llm, max_iterations=3)

    assert result.status == "completed"
    assert sleeps == [1.0]


def test_non_retryable_error_no_sleep_no_escalation(monkeypatch, tmp_path):
    """A deterministic 4xx fails the worker with no sleep recorded."""
    llm = _ScriptedWorkerLLM([_bad_request_error()])

    result, sleeps = _run_worker(monkeypatch, tmp_path, llm, max_iterations=3)

    assert result.status == "failed"
    assert sleeps == []


def test_retry_after_honored(monkeypatch, tmp_path):
    """A 429 with Retry-After: 7 sleeps exactly 7 seconds."""
    llm = _ScriptedWorkerLLM([_rate_limit_error("7")])

    result, sleeps = _run_worker(monkeypatch, tmp_path, llm)

    assert result.status == "completed"
    assert sleeps == [7.0]


def test_retry_after_clamped_to_max(monkeypatch, tmp_path):
    """A Retry-After larger than the configured cap is clamped to the cap."""
    llm = _ScriptedWorkerLLM([_rate_limit_error("500")])

    result, sleeps = _run_worker(monkeypatch, tmp_path, llm)

    assert result.status == "completed"
    assert sleeps == [8.0]


def test_garbage_retry_after_falls_back_to_backoff(monkeypatch, tmp_path):
    """A non-numeric Retry-After header falls back to the exponential delay."""
    llm = _ScriptedWorkerLLM([_rate_limit_error("soon")])

    result, sleeps = _run_worker(monkeypatch, tmp_path, llm)

    assert result.status == "completed"
    assert sleeps == [1.0]


# ---------------------------------------------------------------------------
# Provider layer: Retry-After extraction on ProviderStreamError
# ---------------------------------------------------------------------------


def test_retry_after_s_none_for_connection_reset():
    """A header-less transport error (connection reset) yields retry_after_s=None."""
    err = ProviderStreamError(
        provider="openrouter",
        model="test-model",
        original=ConnectionResetError("connection reset by peer"),
    )

    assert err.retry_after_s is None


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (None, None),
        (types.SimpleNamespace(headers={}), None),
        (types.SimpleNamespace(headers={"Retry-After": "7"}), 7.0),
        (types.SimpleNamespace(headers={"Retry-After": "0"}), 0.0),
        (types.SimpleNamespace(headers={"Retry-After": "soon"}), None),
        (types.SimpleNamespace(headers={"Retry-After": "-3"}), None),
    ],
)
def test_retry_after_s_extraction(response, expected):
    """retry_after_s is the parsed non-negative float, or None when unusable."""
    original = Exception("boom")
    if response is not None:
        original.response = response  # type: ignore[attr-defined]

    err = ProviderStreamError(provider="openrouter", model="test-model", original=original)

    assert err.retry_after_s == expected


# ---------------------------------------------------------------------------
# AgentLoop site
# ---------------------------------------------------------------------------


class _FlakyLoopLLM:
    """LLM stub raising queued errors from stream_chat before succeeding."""

    def __init__(self, errors: list[Exception], final_content: str) -> None:
        """Initialize the flaky stub.

        Args:
            errors: Exceptions raised by successive ``stream_chat`` calls,
                consumed in order before any success.
            final_content: Content of the response returned once the error
                queue is drained.
        """
        self._errors = list(errors)
        self._final_content = final_content
        self.calls = 0

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
        on_reasoning_chunk: Callable[[str], None] | None = None,
        timeout: int | None = None,
        idle_timeout_s: float | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> LLMResponse:
        """Raise the next queued error or return the final response."""
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)
        return LLMResponse(content=self._final_content)

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> LLMResponse:
        """Return an empty non-streaming response (unused)."""
        return LLMResponse(content="")


def _run_loop(
    monkeypatch,
    tmp_path: Path,
    llm: _FlakyLoopLLM,
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any], list[float]]:
    """Run an AgentLoop turn, recording sleep durations.

    Args:
        monkeypatch: pytest monkeypatch fixture (patches sleep + delay knobs).
        tmp_path: Scratch run directory.
        llm: The scripted LLM stub.
        events: Optional event sink collecting ``(event_type, data)`` tuples.

    Returns:
        Tuple of ``(result, sleeps)``.
    """
    from src.agent.loop import AgentLoop
    from src.memory.persistent import PersistentMemory
    from src.tools import build_registry

    sleeps: list[float] = []
    monkeypatch.setattr(loop_mod._time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(loop_mod, "STREAM_RETRY_DELAY_S", 1.0)
    monkeypatch.setattr(loop_mod, "STREAM_RETRY_MAX_DELAY_S", 8.0)
    pm = PersistentMemory()
    agent = AgentLoop(
        registry=build_registry(persistent_memory=pm, include_shell_tools=False),
        llm=llm,
        event_callback=(
            (lambda event_type, data: events.append((event_type, data)))
            if events is not None
            else None
        ),
        max_iterations=3,
        persistent_memory=pm,
    )
    # The retry delay is served by ``self._cancel_event.wait(...)``, not
    # ``time.sleep``: the escalated delay reaches 30s by default and Stop must
    # be observed the moment it is set, not one full delay later. Record that
    # wait so the assertions below still read as "we waited N seconds".
    _real_wait = agent._cancel_event.wait

    def _record_wait(timeout=None):  # noqa: ANN001 - test seam
        if timeout is not None:
            sleeps.append(timeout)
        return _real_wait(0)

    monkeypatch.setattr(agent._cancel_event, "wait", _record_wait)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    agent.memory.run_dir = str(run_dir)
    return agent.run(user_message="hello"), sleeps


def test_loop_first_failure_sleeps_base(monkeypatch, tmp_path: Path) -> None:
    """One transient failure in AgentLoop → exactly one sleep of base (1.0)."""
    llm = _FlakyLoopLLM([_transient_error()], "Final answer.")

    result, sleeps = _run_loop(monkeypatch, tmp_path, llm)

    assert result["status"] == "success"
    assert llm.calls == 2
    assert sleeps == [1.0]


def test_loop_retry_after_honored_and_emitted(monkeypatch, tmp_path: Path) -> None:
    """A 429 with Retry-After: 7 sleeps 7s and emits retry_delay_s=7.0."""
    llm = _FlakyLoopLLM([_rate_limit_error("7")], "Final answer.")
    events: list[tuple[str, dict[str, Any]]] = []

    result, sleeps = _run_loop(monkeypatch, tmp_path, llm, events)

    assert result["status"] == "success"
    assert sleeps == [7.0]
    reset = next(data for event_type, data in events if event_type == "stream_reset")
    assert reset["retry_delay_s"] == 7.0


def test_loop_non_retryable_error_no_sleep(monkeypatch, tmp_path: Path) -> None:
    """A deterministic 4xx fails the loop with no sleep recorded."""
    llm = _FlakyLoopLLM([_bad_request_error()], "Final answer.")

    result, sleeps = _run_loop(monkeypatch, tmp_path, llm)

    assert result["status"] == "failed"
    assert result["error_code"] == "provider_stream_error"
    assert sleeps == []


def test_loop_backoff_helper_escalates_and_caps(monkeypatch) -> None:
    """The loop's capped-exponential helper escalates 1→2→4 and caps at max."""
    monkeypatch.setattr(loop_mod, "STREAM_RETRY_DELAY_S", 1.0)
    monkeypatch.setattr(loop_mod, "STREAM_RETRY_MAX_DELAY_S", 8.0)

    assert loop_mod._stream_retry_backoff_s(1) == 1.0
    assert loop_mod._stream_retry_backoff_s(2) == 2.0
    assert loop_mod._stream_retry_backoff_s(3) == 4.0
    assert loop_mod._stream_retry_backoff_s(7) == 8.0


# ---------------------------------------------------------------------------
# Config knobs and validation
# ---------------------------------------------------------------------------


def test_retry_delay_knob_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both new max-delay knobs default to 30.0 seconds."""
    for alias in (
        "SWARM_STREAM_RETRY_DELAY_S",
        "SWARM_STREAM_RETRY_MAX_DELAY_S",
        "VT_STREAM_RETRY_DELAY_S",
        "VT_STREAM_RETRY_MAX_DELAY_S",
    ):
        monkeypatch.delenv(alias, raising=False)

    assert SwarmConfig().swarm_stream_retry_max_delay_s == 30.0
    assert AgentTuningConfig().vt_stream_retry_max_delay_s == 30.0


def test_swarm_stream_retry_max_below_base_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """SWARM_STREAM_RETRY_MAX_DELAY_S < SWARM_STREAM_RETRY_DELAY_S is rejected."""
    with pytest.raises(ValidationError):
        SwarmConfig(swarm_stream_retry_delay_s=5.0, swarm_stream_retry_max_delay_s=2.0)


def test_swarm_worker_retry_pair_still_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pre-existing worker retry max>=base validation is preserved."""
    with pytest.raises(ValidationError):
        SwarmConfig(swarm_worker_retry_base_delay_s=40.0)


def test_vt_stream_retry_max_below_base_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """VT_STREAM_RETRY_MAX_DELAY_S < VT_STREAM_RETRY_DELAY_S is rejected."""
    with pytest.raises(ValidationError):
        AgentTuningConfig(vt_stream_retry_delay_s=5.0, vt_stream_retry_max_delay_s=2.0)


# ---------------------------------------------------------------------------
# Cancellation during the (now much longer) retry delay
# ---------------------------------------------------------------------------


def test_loop_cancel_during_retry_delay_returns_without_waiting_it_out(
    monkeypatch, tmp_path: Path
) -> None:
    """Stop pressed during the backoff must not be held for the whole delay.

    The delay used to be a flat 1.0s constant; it now escalates to the
    configured cap and a provider Retry-After can ask for the cap on the very
    first failure. A blocking ``time.sleep`` would make Stop take that long to
    be observed, and would still issue the retry stream afterwards.
    """
    llm = _FlakyLoopLLM([_transient_error()], "Final answer.")

    from src.agent.loop import AgentLoop
    from src.memory.persistent import PersistentMemory
    from src.tools import build_registry

    monkeypatch.setattr(loop_mod, "STREAM_RETRY_DELAY_S", 30.0)
    monkeypatch.setattr(loop_mod, "STREAM_RETRY_MAX_DELAY_S", 30.0)
    pm = PersistentMemory()
    agent = AgentLoop(
        registry=build_registry(persistent_memory=pm, include_shell_tools=False),
        llm=llm,
        max_iterations=3,
        persistent_memory=pm,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    agent.memory.run_dir = str(run_dir)

    waited: list[float] = []
    _real_wait = agent._cancel_event.wait

    def _cancel_on_wait(timeout=None):  # noqa: ANN001 - test seam
        if timeout is not None:
            waited.append(timeout)
        agent._cancel_event.set()  # the user presses Stop mid-backoff
        return _real_wait(0)

    monkeypatch.setattr(agent._cancel_event, "wait", _cancel_on_wait)

    start = _perf()
    agent.run(user_message="hello")
    elapsed = _perf() - start

    assert waited == [30.0]  # the escalated delay was asked for
    assert elapsed < 5.0  # ...but never actually served
    assert llm.calls == 1  # the doomed retry stream was never issued
