"""A silent provider stream must be interruptible and must release its transport.

The old loop checked the idle timeout and the cancel predicate only *after* a
chunk arrived, so a provider that stopped sending held the caller forever and a
stop request could not reach it. These tests pin the supervision contract: the
wait for the next chunk is raced against the deadline and the cancel signal,
and stopping really closes the stream rather than abandoning a thread.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from src.providers.chat import ChatLLM


class _Chunk:
    def __init__(self, content: str = "", finish_reason: str = "stop") -> None:
        self.content = content
        self.tool_calls: list[dict[str, Any]] = []
        self.additional_kwargs: dict[str, Any] = {}
        self.response_metadata = {"finish_reason": finish_reason}
        self.usage_metadata = None

    def __add__(self, other: "_Chunk") -> "_Chunk":
        return _Chunk(self.content + other.content, other.response_metadata.get("finish_reason", "stop"))


class _SilentStream:
    """A stream whose first chunk only arrives when the test releases it."""

    def __init__(self, *, chunk: _Chunk | None = None, hold: float = 3.0) -> None:
        self.chunk = chunk
        self.hold = hold
        self.closed = False
        self.close_count = 0
        self.released = threading.Event()

    def __iter__(self):
        return self

    def __next__(self) -> _Chunk:
        if self.closed:
            raise StopIteration
        if not self.released.wait(self.hold):
            raise StopIteration
        if self.closed:
            raise StopIteration
        if self.chunk is None:
            raise StopIteration
        chunk, self.chunk = self.chunk, None
        return chunk

    def close(self) -> None:
        self.closed = True
        self.close_count += 1
        self.released.set()


class _FakeLLM:
    def __init__(self, stream: _SilentStream) -> None:
        self.stream_obj = stream
        self.invoke_called = 0

    def bind_tools(self, tools):
        return self

    def stream(self, messages, config=None, **kwargs):
        return self.stream_obj

    def invoke(self, messages, config=None, **kwargs):
        self.invoke_called += 1
        return _Chunk("fallback")


def _client(stream: _SilentStream) -> ChatLLM:
    client = ChatLLM.__new__(ChatLLM)
    client.model_name = "fake"
    client._llm = _FakeLLM(stream)
    return client


def test_idle_timeout_interrupts_a_silent_stream() -> None:
    stream = _SilentStream()
    started = time.monotonic()

    with pytest.raises(Exception):
        _client(stream).stream_chat(
            [{"role": "user", "content": "hi"}],
            idle_timeout_s=0.15,
        )

    assert time.monotonic() - started < 5
    assert stream.closed, "the stream must be closed, not merely abandoned"


def test_cancel_interrupts_a_silent_stream() -> None:
    stream = _SilentStream()
    cancel = threading.Event()
    threading.Timer(0.15, cancel.set).start()
    started = time.monotonic()

    response = _client(stream).stream_chat(
        [{"role": "user", "content": "hi"}],
        should_cancel=cancel.is_set,
    )

    assert time.monotonic() - started < 5
    assert stream.closed
    assert response.content == ""


def test_total_timeout_interrupts_a_silent_stream() -> None:
    stream = _SilentStream()
    started = time.monotonic()

    with pytest.raises(Exception):
        _client(stream).stream_chat(
            [{"role": "user", "content": "hi"}],
            timeout=1,
        )

    assert time.monotonic() - started < 5
    assert stream.closed


def test_no_replay_after_an_interrupted_stream() -> None:
    """A cancelled or timed-out stream must not fall back and resend the request."""
    stream = _SilentStream()
    client = _client(stream)
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()

    client.stream_chat([{"role": "user", "content": "hi"}], should_cancel=cancel.is_set)

    assert client._llm.invoke_called == 0


def test_no_replay_after_partial_output() -> None:
    """Once text has been emitted a fallback invoke would replay the turn."""
    stream = _SilentStream(chunk=_Chunk("partial"))
    client = _client(stream)

    with pytest.raises(Exception):
        client.stream_chat(
            [{"role": "user", "content": "hi"}],
            on_text_chunk=lambda text: None,
            idle_timeout_s=0.2,
        )

    assert client._llm.invoke_called == 0


def test_a_late_chunk_after_cancel_never_reaches_the_caller() -> None:
    stream = _SilentStream()
    client = _client(stream)
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    seen: list[str] = []

    client.stream_chat(
        [{"role": "user", "content": "hi"}],
        on_text_chunk=seen.append,
        should_cancel=cancel.is_set,
    )
    stream.released.set()
    time.sleep(0.2)

    assert seen == []


def test_a_delivered_stream_still_reports_its_answer() -> None:
    stream = _SilentStream(chunk=_Chunk("hello"))
    stream.released.set()
    client = _client(stream)

    response = client.stream_chat([{"role": "user", "content": "hi"}], idle_timeout_s=5)

    assert response.content == "hello"
    assert client._llm.invoke_called == 0


def test_slow_consumer_preserves_every_chunk_and_eof():
    from src.providers.stream_guard import supervised_pulls

    chunks = supervised_pulls(iter(range(4)), idle_timeout_s=0.2)
    assert next(chunks) == 0
    time.sleep(1.2)  # Exceeds the old queue put timeout and idle threshold.
    assert list(chunks) == [1, 2, 3]


def test_pull_thread_keeps_session_context():
    import contextvars
    from src.providers.stream_guard import supervised_pulls

    session = contextvars.ContextVar("test_stream_session", default=None)
    token = session.set("session-123")
    try:
        def stream():
            yield session.get()
        assert list(supervised_pulls(stream(), idle_timeout_s=1)) == ["session-123"]
    finally:
        session.reset(token)


def test_busy_generator_is_closed_when_pending_pull_returns():
    from src.providers.stream_guard import StreamInterrupted, supervised_pulls

    released, closed = threading.Event(), threading.Event()
    def stream():
        try:
            released.wait(2)
            yield "late"
        finally:
            closed.set()
    try:
        with pytest.raises(StreamInterrupted, match="idle timeout"):
            list(supervised_pulls(stream(), idle_timeout_s=0.05))
    finally:
        released.set()
    assert closed.wait(2)


def test_consumer_exception_closes_stream():
    stream = _SilentStream(chunk=_Chunk("hello"))
    stream.released.set()
    def fail(text):
        raise RuntimeError("consumer failed")
    with pytest.raises(Exception, match="consumer failed"):
        _client(stream).stream_chat([], idle_timeout_s=1, on_text_chunk=fail)
    assert stream.closed


def test_partial_stream_no_chunk_error_never_replays():
    from langchain_core.messages import AIMessageChunk
    class Provider:
        invoke_called = False
        def stream(self, *args, **kwargs):
            yield AIMessageChunk(content="partial")
            raise ValueError("No generation chunks were returned")
        def invoke(self, *args, **kwargs):
            self.invoke_called = True
            return AIMessageChunk(content="replayed")
    provider = Provider()
    client = _client(_SilentStream())
    client._llm = provider
    with pytest.raises(Exception):
        client.stream_chat([], idle_timeout_s=1)
    assert not provider.invoke_called
