"""AgentLoop single stream retry on ProviderStreamError.

Mirrors the swarm worker policy: a transient mid-stream failure (connection
reset, relay hiccup, 5xx) is retried exactly once; a deterministic 4xx fails
the run immediately with error_code=provider_stream_error and no wasted
request. Deltas from the failed attempt are dropped so the trace does not
contain duplicated thinking text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

import src.agent.loop as loop_mod
from src.providers.chat import LLMResponse, ProviderStreamError


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
        should_cancel: Callable[[], bool] | None = None,
    ) -> LLMResponse:
        """Raise the next queued error or return the final response.

        Args:
            messages: Conversation messages (ignored).
            tools: Tool definitions (ignored).
            on_text_chunk: Text streaming callback; fires before a queued
                error so the dropped-delta behavior is observable.
            on_reasoning_chunk: Reasoning callback (ignored).

        Returns:
            The scripted final ``LLMResponse``.

        Raises:
            Exception: The next queued error, if any remain.
        """
        self.calls += 1
        if self._errors:
            if on_text_chunk:
                on_text_chunk("partial-from-failed-attempt ")
            raise self._errors.pop(0)
        if on_text_chunk:
            on_text_chunk(self._final_content)
        return LLMResponse(content=self._final_content)

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> LLMResponse:
        """Return an empty non-streaming response (unused).

        Args:
            messages: Conversation messages (ignored).

        Returns:
            Empty ``LLMResponse``.
        """
        return LLMResponse(content="")


def _transient_error() -> ProviderStreamError:
    """Build a ProviderStreamError mimicking a transient mid-stream reset.

    Returns:
        ProviderStreamError wrapping a ``ConnectionResetError`` (no status).
    """
    return ProviderStreamError(
        provider="deepseek",
        model="deepseek-v4-pro",
        original=ConnectionResetError("connection reset by peer"),
    )


def _bad_request_error() -> ProviderStreamError:
    """Build a ProviderStreamError mimicking a deterministic 400 rejection.

    Returns:
        ProviderStreamError whose original exception carries status_code=400.
    """
    original = Exception("invalid temperature: only 1 is allowed for this model")
    original.status_code = 400  # type: ignore[attr-defined]
    return ProviderStreamError(
        provider="moonshot", model="kimi-k2.6", original=original
    )


def _run(
    monkeypatch,
    tmp_path: Path,
    llm: _FlakyLoopLLM,
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run an AgentLoop turn against the given scripted LLM.

    Args:
        monkeypatch: pytest monkeypatch fixture (zeroes the retry sleep).
        tmp_path: Scratch run directory.
        llm: The scripted LLM stub.
        events: Optional event sink collecting ``(event_type, data)`` tuples.

    Returns:
        The AgentLoop result dict.
    """
    from src.agent.loop import AgentLoop
    from src.memory.persistent import PersistentMemory
    from src.tools import build_registry

    monkeypatch.setattr(loop_mod, "STREAM_RETRY_DELAY_S", 0.0)
    # Legacy tests assert the historical single-retry behaviour; the new
    # default (VT_STREAM_MAX_RETRIES=3) is covered by tests below.
    monkeypatch.setattr(loop_mod, "STREAM_MAX_RETRIES", 1)
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
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    agent.memory.run_dir = str(run_dir)
    return agent.run(user_message="hello")


def test_transient_stream_failure_is_retried_and_run_succeeds(
    monkeypatch, tmp_path: Path
) -> None:
    """One transient ProviderStreamError then success → run completes (2 calls)."""
    llm = _FlakyLoopLLM([_transient_error()], "Final answer.")
    events: list[tuple[str, dict[str, Any]]] = []

    result = _run(monkeypatch, tmp_path, llm, events)

    assert result["status"] == "success"
    assert result["content"] == "Final answer."
    assert llm.calls == 2

    event_types = [event_type for event_type, _ in events]
    assert "stream_reset" in event_types
    text_positions = [
        index for index, event_type in enumerate(event_types) if event_type == "text_delta"
    ]
    reset_position = event_types.index("stream_reset")
    assert text_positions[0] < reset_position < text_positions[-1]
    reset = next(data for event_type, data in events if event_type == "stream_reset")
    assert reset["reason"] == "provider_stream_retry"
    assert reset["iter"] == 1
    assert reset["provider"] == "deepseek"
    assert reset["model"] == "deepseek-v4-pro"


def test_double_stream_failure_fails_run(monkeypatch, tmp_path: Path) -> None:
    """Two consecutive transient failures → failed run, no third attempt."""
    llm = _FlakyLoopLLM([_transient_error(), _transient_error()], "Final answer.")

    result = _run(monkeypatch, tmp_path, llm)

    assert result["status"] == "failed"
    assert result["error_code"] == "provider_stream_error"
    assert llm.calls == 2


def test_non_retryable_4xx_fails_without_retry(monkeypatch, tmp_path: Path) -> None:
    """A deterministic 4xx ProviderStreamError fails immediately (1 call)."""
    llm = _FlakyLoopLLM([_bad_request_error()], "Final answer.")

    result = _run(monkeypatch, tmp_path, llm)

    assert result["status"] == "failed"
    assert result["error_code"] == "provider_stream_error"
    assert llm.calls == 1


def _remote_protocol_error() -> ProviderStreamError:
    """Build a ProviderStreamError mimicking httpx RemoteProtocolError.

    Mirrors the regression observed in session 86171649b571 (2026-07-14):
    minimax returns HTTP 200 then closes the chunked body mid-stream,
    which httpx surfaces as ``RemoteProtocolError: incomplete chunked read``.
    """
    try:
        import httpx

        original = httpx.RemoteProtocolError(
            "peer closed connection without sending complete message body "
            "(incomplete chunked read)"
        )
    except ImportError:  # pragma: no cover — httpx is a runtime dep
        original = ConnectionResetError("peer closed connection mid-chunked-body")
    return ProviderStreamError(provider="minimax", model="MiniMax-M3", original=original)


def test_remote_protocol_error_is_retried_until_success(
    monkeypatch, tmp_path: Path
) -> None:
    """httpx RemoteProtocolError (no status_code) is retryable — succeeds after 2 retries.

    Regression for session 86171649b571 attempt 6c91a7707761: minimax relay
    closed the chunked body mid-stream. With VT_STREAM_MAX_RETRIES=3 the
    second attempt succeeds.
    """
    from src.agent.loop import AgentLoop
    from src.memory.persistent import PersistentMemory
    from src.tools import build_registry

    monkeypatch.setattr(loop_mod, "STREAM_RETRY_DELAY_S", 0.0)
    monkeypatch.setattr(loop_mod, "STREAM_MAX_RETRIES", 3)
    llm = _FlakyLoopLLM(
        [_remote_protocol_error(), _remote_protocol_error()],
        "Final answer after two RemoteProtocolErrors.",
    )
    events: list[tuple[str, dict[str, Any]]] = []
    pm = PersistentMemory()
    agent = AgentLoop(
        registry=build_registry(persistent_memory=pm, include_shell_tools=False),
        llm=llm,
        event_callback=lambda event_type, data: events.append((event_type, data)),
        max_iterations=3,
        persistent_memory=pm,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    agent.memory.run_dir = str(run_dir)

    result = agent.run(user_message="hello")

    assert result["status"] == "success"
    assert "two RemoteProtocolErrors" in result["content"]
    assert llm.calls == 3  # 1 initial + 2 retries + 1 success

    resets = [data for event_type, data in events if event_type == "stream_reset"]
    assert len(resets) == 2
    for reset in resets:
        assert reset["reason"] == "provider_stream_retry"
        assert reset["provider"] == "minimax"
        assert reset["model"] == "MiniMax-M3"
        assert reset["max_attempts"] == 4  # 3 retries + 1 initial
    assert resets[0]["attempt"] == 1
    assert resets[1]["attempt"] == 2


def test_remote_protocol_error_exhausts_retries_and_fails(
    monkeypatch, tmp_path: Path
) -> None:
    """With VT_STREAM_MAX_RETRIES=3, four consecutive RemoteProtocolErrors fail."""
    from src.agent.loop import AgentLoop
    from src.memory.persistent import PersistentMemory
    from src.tools import build_registry

    monkeypatch.setattr(loop_mod, "STREAM_RETRY_DELAY_S", 0.0)
    monkeypatch.setattr(loop_mod, "STREAM_MAX_RETRIES", 3)
    llm = _FlakyLoopLLM(
        [_remote_protocol_error()] * 4,  # 1 initial + 3 retries all fail
        "Final answer.",
    )
    pm = PersistentMemory()
    agent = AgentLoop(
        registry=build_registry(persistent_memory=pm, include_shell_tools=False),
        llm=llm,
        event_callback=None,
        max_iterations=3,
        persistent_memory=pm,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    agent.memory.run_dir = str(run_dir)

    result = agent.run(user_message="hello")

    assert result["status"] == "failed"
    assert result["error_code"] == "provider_stream_error"
    assert llm.calls == 4  # 1 initial + 3 retries
    assert "RemoteProtocolError" in result["reason"]


class _CancellingFlakyLLM:
    """LLM stub that cancels the loop on the first stream_chat, then keeps failing.

    Mimics a user cancel arriving while a transient stream error is being
    retried: the retry loop must honour the cancel and stop calling
    ``stream_chat`` for further attempts.
    """

    def __init__(
        self,
        agent_ref: "list[AgentLoop]",
        errors: list[Exception],
    ) -> None:
        self._agent_ref = agent_ref
        self._errors = list(errors)
        self.calls = 0

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
        on_reasoning_chunk: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> LLMResponse:
        self.calls += 1
        if self._errors:
            # Set the cancel before raising the queued error. The retry
            # loop must observe the cancel and abort without burning the
            # full retry budget on the next attempt.
            if self.calls == 1:
                self._agent_ref[0]._cancel_event.set()
            raise self._errors.pop(0)
        return LLMResponse(content="Should never reach here.")

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> LLMResponse:
        return LLMResponse(content="")


def test_cancel_during_stream_retry_stops_retry_loop(
    monkeypatch, tmp_path: Path
) -> None:
    """Cancel set during a failed stream attempt aborts before the next retry.

    Regression guard: previously the retry loop had no cancel checkpoint
    and could spend the full retry budget (~3s default) before raising.
    With the fix, a cancel observed inside the ``except ProviderStreamError``
    branch (or at the top of the next iteration) exits cleanly.
    """
    from src.agent.loop import AgentLoop
    from src.memory.persistent import PersistentMemory
    from src.tools import build_registry

    monkeypatch.setattr(loop_mod, "STREAM_RETRY_DELAY_S", 0.0)
    monkeypatch.setattr(loop_mod, "STREAM_MAX_RETRIES", 3)
    agent_ref: list[AgentLoop] = []
    llm = _CancellingFlakyLLM(
        agent_ref,
        [_transient_error()] * 4,  # would otherwise run 4 calls
    )
    pm = PersistentMemory()
    agent = AgentLoop(
        registry=build_registry(persistent_memory=pm, include_shell_tools=False),
        llm=llm,
        event_callback=None,
        max_iterations=3,
        persistent_memory=pm,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    agent.memory.run_dir = str(run_dir)
    agent_ref.append(agent)

    result = agent.run(user_message="hello")

    assert result["status"] == "cancelled"
    assert result["reason"] == "cancelled by user"
    # Only the initial stream_chat call should have been made - the retry
    # loop must short-circuit on the observed cancel rather than spending
    # the full retry budget on follow-up attempts.
    assert llm.calls == 1


class _CancelThenProviderErrorLLM:
    """LLM stub that sets cancel then raises ProviderStreamError.

    Exercises the outer ``except`` branch: a provider error that surfaces
    after the user has cancelled must be reported as 'cancelled', not as
    a generic provider_stream_error failure.
    """

    def __init__(self, agent_ref: "list[AgentLoop]") -> None:
        self._agent_ref = agent_ref

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
        on_reasoning_chunk: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> LLMResponse:
        # Non-retryable 4xx mimics a deterministic provider error raised in
        # response to a cancel signal. The outer except must observe the
        # cancel state and report 'cancelled' instead of 'failed'.
        self._agent_ref[0]._cancel_event.set()
        raise _bad_request_error()

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> LLMResponse:
        return LLMResponse(content="")


def test_provider_error_after_cancel_reports_cancelled(
    monkeypatch, tmp_path: Path
) -> None:
    """ProviderStreamError raised after cancel - result is 'cancelled'.

    Regression guard: the outer except block previously mapped any
    ProviderStreamError to status='failed' / error_code='provider_stream_error'
    regardless of whether the user had cancelled. The fix observes the
    cancel state and surfaces a clean 'cancelled' terminal status.
    """
    from src.agent.loop import AgentLoop
    from src.memory.persistent import PersistentMemory
    from src.tools import build_registry

    monkeypatch.setattr(loop_mod, "STREAM_RETRY_DELAY_S", 0.0)
    monkeypatch.setattr(loop_mod, "STREAM_MAX_RETRIES", 1)
    agent_ref: list[AgentLoop] = []
    llm = _CancelThenProviderErrorLLM(agent_ref)
    pm = PersistentMemory()
    agent = AgentLoop(
        registry=build_registry(persistent_memory=pm, include_shell_tools=False),
        llm=llm,
        event_callback=None,
        max_iterations=3,
        persistent_memory=pm,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    agent.memory.run_dir = str(run_dir)
    agent_ref.append(agent)

    result = agent.run(user_message="hello")

    assert result["status"] == "cancelled"
    assert result["reason"] == "cancelled by user"
    # Must NOT be the provider_stream_error failed branch.
    assert "error_code" not in result or result.get("error_code") != "provider_stream_error"
