"""A silent provider stream must be interruptible and must release its transport.

The old loop checked the idle timeout and the cancel predicate only *after* a
chunk arrived, so a provider that stopped sending held the caller forever and a
stop request could not reach it. These tests pin the supervision contract: the
wait for the next chunk is raced against the deadline and the cancel signal,
and stopping really closes the stream rather than abandoning a thread.
"""

from __future__ import annotations

from tests.provider_helpers import chat_with_adapter

import threading
import time

import pytest
from langchain_core.messages import AIMessageChunk
from src.providers.chat import ProviderStreamError

class _SilentStream:
    """A stream whose first chunk only arrives when the test releases it."""

    def __init__(self, *, chunk: AIMessageChunk | None = None, hold: float = 3.0) -> None:
        self.chunk = chunk
        self.hold = hold
        self.closed = False
        self.close_count = 0
        self.released = threading.Event()

    def __iter__(self):
        return self

    def __next__(self) -> AIMessageChunk:
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
        return AIMessageChunk(content="fallback")


def _client(stream: _SilentStream):
    return chat_with_adapter(_FakeLLM(stream), model="fake")


@pytest.mark.parametrize("stop", ["idle timeout", "total timeout", "cancel"])
def test_silent_stream_stops_closes_and_never_replays_or_delivers_late_text(stop):
    stream = _SilentStream(chunk=AIMessageChunk(content="late"))
    client = _client(stream)
    cancel = threading.Event()
    timer = threading.Timer(0.1, cancel.set)
    options = {"idle_timeout_s": 0.15} if stop == "idle timeout" else {"timeout": 1}
    seen = []
    started = time.monotonic()
    try:
        if stop == "cancel":
            timer.start()
            response = client.stream_chat([], should_cancel=cancel.is_set, on_text_chunk=seen.append)
            assert response.content == "" and not response.tool_calls
        else:
            with pytest.raises(ProviderStreamError, match=stop) as caught:
                client.stream_chat([], on_text_chunk=seen.append, **options)
            assert caught.value.retryable
        assert time.monotonic() - started < 5
        assert stream.closed and stream.close_count == 1
        assert client._llm.invoke_called == 0
        stream.released.set()
        time.sleep(0.05)
        assert seen == []
    finally:
        timer.cancel()
        stream.close()


def test_a_delivered_stream_still_reports_its_answer() -> None:
    stream = _SilentStream(chunk=AIMessageChunk(content="hello"))
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
    stream = _SilentStream(chunk=AIMessageChunk(content="hello"))
    stream.released.set()
    def fail(text):
        raise RuntimeError("consumer failed")
    with pytest.raises(ProviderStreamError, match="consumer failed"):
        _client(stream).stream_chat([], idle_timeout_s=1, on_text_chunk=fail)
    assert stream.closed


def test_partial_stream_no_chunk_error_never_replays():
    class Provider:
        invoke_called = False
        def stream(self, *args, **kwargs):
            yield AIMessageChunk(content="partial")
            raise ValueError("No generation chunks were returned")
        def invoke(self, *args, **kwargs):
            self.invoke_called = True
            return AIMessageChunk(content="replayed")
    provider = Provider()
    client = chat_with_adapter(provider)
    with pytest.raises(ProviderStreamError, match="No generation chunks"):
        client.stream_chat([], idle_timeout_s=1)
    assert not provider.invoke_called


def test_zero_timeout_keeps_the_existing_disabled_convention():
    from src.providers.stream_guard import supervised_pulls
    assert list(supervised_pulls(iter([1, 2]), idle_timeout_s=0, total_timeout_s=0)) == [1, 2]
