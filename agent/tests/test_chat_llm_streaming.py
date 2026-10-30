"""ChatLLM streaming liveness and error semantics."""

from __future__ import annotations

import os
import threading
from typing import Any
from unittest.mock import patch

import pytest

from src.providers.chat import ChatLLM, ProviderStreamError


class _FakeChunk:
    def __init__(
        self,
        *,
        content: str = "",
        reasoning: str = "",
        finish_reason: str = "stop",
    ) -> None:
        self.content = content
        self.tool_calls: list[dict[str, Any]] = []
        self.additional_kwargs = {"reasoning_content": reasoning} if reasoning else {}
        self.response_metadata = {"finish_reason": finish_reason}
        self.usage_metadata = None

    def __add__(self, other: "_FakeChunk") -> "_FakeChunk":
        merged = _FakeChunk(
            content=f"{self.content}{other.content}",
            reasoning=(
                f"{self.additional_kwargs.get('reasoning_content', '')}"
                f"{other.additional_kwargs.get('reasoning_content', '')}"
            ),
            finish_reason=other.response_metadata.get("finish_reason", "stop"),
        )
        return merged


class _FakeStreamingLLM:
    def __init__(self, chunks: list[_FakeChunk] | None = None, exc: Exception | None = None) -> None:
        self.chunks = chunks or []
        self.exc = exc
        self.invoke_called = False

    def bind_tools(self, tools: list[dict[str, Any]]) -> "_FakeStreamingLLM":
        return self

    def stream(self, messages: list[dict[str, Any]], config: dict[str, Any] | None = None):
        if self.exc is not None:
            raise self.exc
        yield from self.chunks

    def invoke(self, messages: list[dict[str, Any]], config: dict[str, Any] | None = None):
        self.invoke_called = True
        return _FakeChunk(content="fallback")


def _client(fake_llm: _FakeStreamingLLM) -> ChatLLM:
    client = ChatLLM.__new__(ChatLLM)
    client.model_name = "deepseek-v4-pro"
    client._llm = fake_llm
    return client


def test_reasoning_only_chunks_emit_progress_without_final_answer_text() -> None:
    fake = _FakeStreamingLLM([
        _FakeChunk(reasoning="thinking "),
        _FakeChunk(reasoning="more"),
        _FakeChunk(content="final"),
    ])
    text_chunks: list[str] = []
    reasoning_chunks: list[str] = []

    response = _client(fake).stream_chat(
        [{"role": "user", "content": "hi"}],
        on_text_chunk=text_chunks.append,
        on_reasoning_chunk=reasoning_chunks.append,
    )

    assert text_chunks == ["final"]
    assert reasoning_chunks == ["thinking ", "more"]
    assert response.content == "final"
    assert response.reasoning_content == "thinking more"


def test_parse_dsml_tool_call_content_as_structured_tool_call() -> None:
    """DeepSeek-style DSML content must drive the ReAct tool path (#261)."""
    content = (
        '<｜｜DSML｜｜tool_calls> '
        '<｜｜DSML｜｜invoke name="bash"> '
        '<｜｜DSML｜｜parameter name="command" string="true">'
        "python -c \"print('vibe-dsml-ok')\""
        "</｜｜DSML｜｜parameter> "
        "</｜｜DSML｜｜invoke> "
        "</｜｜DSML｜｜tool_calls>/"
    )

    response = ChatLLM._parse_response(_FakeChunk(content=content))

    assert response.content == ""
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "dsml_call_1"
    assert response.tool_calls[0].name == "bash"
    assert response.tool_calls[0].arguments == {
        "command": "python -c \"print('vibe-dsml-ok')\""
    }
    assert response.finish_reason == "tool_calls"


def test_parse_dsml_tool_call_requires_pure_tool_call_payload() -> None:
    """Do not execute DSML examples embedded inside normal assistant text."""
    content = (
        "Here is the syntax:\n"
        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="bash">'
        '<｜｜DSML｜｜parameter name="command">pwd</｜｜DSML｜｜parameter>'
        "</｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>"
    )

    response = ChatLLM._parse_response(_FakeChunk(content=content))

    assert response.content == content
    assert response.tool_calls == []
    assert response.finish_reason == "stop"


def test_stream_dsml_tool_call_content_is_not_emitted_as_text() -> None:
    """DSML tool-call payloads should not flash as assistant text in CLI/UI."""
    content = (
        '<｜｜DSML｜｜tool_calls>'
        '<｜｜DSML｜｜invoke name="bash">'
        '<｜｜DSML｜｜parameter name="command">pwd</｜｜DSML｜｜parameter>'
        "</｜｜DSML｜｜invoke>"
        "</｜｜DSML｜｜tool_calls>"
    )
    fake = _FakeStreamingLLM([_FakeChunk(content=content)])
    text_chunks: list[str] = []

    response = _client(fake).stream_chat(
        [{"role": "user", "content": "hi"}],
        on_text_chunk=text_chunks.append,
    )

    assert text_chunks == []
    assert response.content == ""
    assert response.tool_calls[0].name == "bash"


def test_anthropic_content_blocks_stream_with_native_tool_call() -> None:
    chunk = _FakeChunk()
    chunk.content = [
        {"type": "text", "text": "Checking quote"},
        {"type": "tool_use", "id": "toolu_1", "name": "quote", "input": {}},
    ]
    chunk.tool_calls = [
        {"id": "toolu_1", "name": "quote", "args": {"symbol": "AAPL"}},
    ]
    chunk.response_metadata = {"stop_reason": "tool_use"}
    text_chunks: list[str] = []

    response = _client(_FakeStreamingLLM([chunk])).stream_chat(
        [{"role": "user", "content": "quote AAPL"}],
        on_text_chunk=text_chunks.append,
    )

    assert text_chunks == ["Checking quote"]
    assert response.content == "Checking quote"
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].id == "toolu_1"
    assert response.tool_calls[0].arguments == {"symbol": "AAPL"}


def test_should_cancel_stops_stream_early() -> None:
    """A should_cancel predicate breaks the chunk loop; later chunks are dropped."""
    fake = _FakeStreamingLLM([
        _FakeChunk(content="a"),
        _FakeChunk(content="b"),
        _FakeChunk(content="c"),
    ])
    seen: list[str] = []
    cancelled = threading.Event()

    def should_cancel() -> bool:
        # Let the first chunk through, then stop. Signalled from the delivery
        # callback rather than counted here: the supervisor polls this while a
        # stream is silent, so a call-counting predicate would fire before the
        # first chunk purely from the polling cadence.
        return cancelled.is_set()

    def on_text(text: str) -> None:
        seen.append(text)
        cancelled.set()

    response = _client(fake).stream_chat(
        [{"role": "user", "content": "hi"}],
        on_text_chunk=on_text,
        should_cancel=should_cancel,
    )

    assert seen == ["a"]
    assert response.content == "a"


def test_should_cancel_absent_consumes_full_stream() -> None:
    """Without should_cancel the stream is consumed in full (no behavior change)."""
    fake = _FakeStreamingLLM([_FakeChunk(content="x"), _FakeChunk(content="y")])
    seen: list[str] = []

    response = _client(fake).stream_chat(
        [{"role": "user", "content": "hi"}],
        on_text_chunk=seen.append,
    )

    assert seen == ["x", "y"]
    assert response.content == "xy"


def test_stream_failure_raises_provider_error_without_silent_fallback() -> None:
    fake = _FakeStreamingLLM(exc=RuntimeError("stream exploded"))

    with patch.dict(
        os.environ,
        {"LANGCHAIN_PROVIDER": "deepseek", "LANGCHAIN_MODEL_NAME": "deepseek-v4-pro"},
        clear=True,
    ):
        with pytest.raises(ProviderStreamError) as excinfo:
            _client(fake).stream_chat([{"role": "user", "content": "hi"}])

    assert "provider=deepseek" in str(excinfo.value)
    assert "model=deepseek-v4-pro" in str(excinfo.value)
    assert fake.invoke_called is False


def test_stream_error_redacts_configured_secret_values() -> None:
    fake = _FakeStreamingLLM(exc=RuntimeError("bad key sk-live-secret-123456"))

    with patch.dict(
        os.environ,
        {
            "LANGCHAIN_PROVIDER": "deepseek",
            "LANGCHAIN_MODEL_NAME": "deepseek-v4-pro",
            "DEEPSEEK_API_KEY": "sk-live-secret-123456",
        },
        clear=True,
    ):
        with pytest.raises(ProviderStreamError) as excinfo:
            _client(fake).stream_chat([{"role": "user", "content": "hi"}])

    assert "sk-live-secret-123456" not in str(excinfo.value)
    assert "[redacted]" in str(excinfo.value)


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (None, True),   # transport error, no HTTP status — plausibly transient
        (400, False),   # deterministic client error
        (401, False),
        (404, False),
        (408, True),    # request timeout — transient
        (429, True),    # rate limit — transient
        (500, True),
        (503, True),
    ],
)
def test_provider_stream_error_retryable_classification(
    status_code: int | None, expected: bool
) -> None:
    original = Exception("boom")
    if status_code is not None:
        original.status_code = status_code  # type: ignore[attr-defined]
    err = ProviderStreamError(provider="kimi", model="kimi-k2.6", original=original)
    assert err.status_code == status_code
    assert err.retryable is expected


def test_content_filter_triggered_flag() -> None:
    """content_filter finish_reason sets content_filter_triggered=True."""
    response = ChatLLM._parse_response(
        _FakeChunk(content="", finish_reason="content_filter")
    )

    assert response.content == ""
    assert response.finish_reason == "content_filter"
    assert response.content_filter_triggered is True


def test_content_filter_triggered_flag_false_on_stop() -> None:
    """Normal stop reason leaves content_filter_triggered=False."""
    response = ChatLLM._parse_response(
        _FakeChunk(content="text", finish_reason="stop")
    )

    assert response.content == "text"
    assert response.finish_reason == "stop"
    assert response.content_filter_triggered is False


# ---------------------------------------------------------------------------
# #758: no-SSE endpoints (e.g. some Z.ai coding-plan routes) stream zero
# chunks; stream_chat must fall back to a non-streaming invoke, and a bare
# base-URL misconfiguration must surface an actionable hint.
# ---------------------------------------------------------------------------


def test_empty_stream_value_error_falls_back_to_invoke() -> None:
    """LangChain's 'No generation chunks were returned' → non-streaming invoke."""
    fake = _FakeStreamingLLM(exc=ValueError("No generation chunks were returned"))
    response = _client(fake).stream_chat([{"role": "user", "content": "hi"}])
    assert fake.invoke_called is True
    assert response.content == "fallback"


def test_clean_zero_chunk_stream_falls_back_to_invoke() -> None:
    """A stream that ends cleanly with no chunks (and no cancel) also falls back."""
    fake = _FakeStreamingLLM(chunks=[])
    response = _client(fake).stream_chat([{"role": "user", "content": "hi"}])
    assert fake.invoke_called is True
    assert response.content == "fallback"


def test_generic_value_error_still_raises_provider_error() -> None:
    """A ValueError that is NOT the empty-stream signal still surfaces as error."""
    fake = _FakeStreamingLLM(exc=ValueError("malformed request payload"))
    with patch.dict(
        os.environ,
        {"LANGCHAIN_PROVIDER": "zai", "LANGCHAIN_MODEL_NAME": "glm-5.1"},
        clear=True,
    ):
        with pytest.raises(ProviderStreamError):
            _client(fake).stream_chat([{"role": "user", "content": "hi"}])
    assert fake.invoke_called is False


def test_cancelled_empty_stream_returns_empty_without_fallback() -> None:
    """A user cancel before any chunk returns empty — it must NOT invoke."""
    fake = _FakeStreamingLLM([_FakeChunk(content="ignored")])
    response = _client(fake).stream_chat(
        [{"role": "user", "content": "hi"}], should_cancel=lambda: True
    )
    assert fake.invoke_called is False
    assert response.content == ""


def test_provider_stream_error_hints_at_base_url_on_html_body() -> None:
    """An HTML error page (site root, not API root) appends a base-URL hint."""
    original = RuntimeError(
        '<!DOCTYPE html><html id="__next_error__">404 Not Found</html>'
    )
    err = ProviderStreamError(provider="zai", model="glm-5.1", original=original)
    message = str(err)
    assert "HTML page" in message
    assert "base URL" in message
    assert "zai" in message


def test_stream_idle_timeout_aborts_a_stalled_stream() -> None:
    """A stream whose deltas stall past the idle budget fails retryably.

    The loop passes idle_timeout_s so a provider that stops emitting
    chunks (silent stall) surfaces as a retryable ProviderStreamError
    instead of hanging the run indefinitely.
    """
    import time

    class _StallingLLM(_FakeStreamingLLM):
        def stream(self, messages, config=None):
            yield _FakeChunk(content="first")
            time.sleep(0.6)  # longer than idle_timeout_s below
            yield _FakeChunk(content="second")

    client = _client(_StallingLLM())
    with pytest.raises(ProviderStreamError) as excinfo:
        client.stream_chat(
            [{"role": "user", "content": "hi"}],
            idle_timeout_s=0.2,
        )
    assert excinfo.value.retryable is True


def test_stream_idle_timeout_allows_a_flowing_stream() -> None:
    """Chunks arriving within the idle budget are unaffected by the timeout."""
    import time

    class _FlowingLLM(_FakeStreamingLLM):
        def stream(self, messages, config=None):
            yield _FakeChunk(content="a")
            time.sleep(0.05)
            yield _FakeChunk(content="b")

    client = _client(_FlowingLLM())
    response = client.stream_chat(
        [{"role": "user", "content": "hi"}],
        idle_timeout_s=0.2,
    )
    assert response.content == "ab"



def test_only_explicit_provider_waiting_reaches_activity_callback():
    from langchain_core.messages import AIMessageChunk

    waiting = []
    response = _client(_FakeStreamingLLM([
        AIMessageChunk(content=""),
        AIMessageChunk(content="", additional_kwargs={"provider_waiting": True}),
        AIMessageChunk(content="final"),
    ])).stream_chat([{"role": "user", "content": "q"}], on_waiting_chunk=lambda: waiting.append(True))
    assert waiting == [True]
    assert response.content == "final"


@pytest.mark.parametrize("terminal", [True, False])
@pytest.mark.parametrize("tool_call", [True, False])
def test_actual_chat_stream_requires_terminal_metadata(terminal, tool_call):
    """Replay a clean EOF through the real SDK; truncated JSON is not a call."""
    import json
    import httpx
    from src.providers.llm import ChatOpenAIWithReasoning

    requests = []
    delta = ({"tool_calls": [{"index": 0, "id": "call-partial", "type": "function",
              "function": {"name": "write_file", "arguments": '{"path":"a.txt"}'}}]}
             if tool_call else {"content": "I will now calculate the answer."})

    def respond(request):
        requests.append(request)
        packets = [{"id": "offline", "object": "chat.completion.chunk", "created": 0,
                    "model": "deepseek-v4-pro", "choices": [{"index": 0, "delta": delta,
                    "finish_reason": None}]}]
        if terminal:
            packets.append({**packets[0], "choices": [{"index": 0, "delta": {},
                            "finish_reason": "tool_calls" if tool_call else "stop"}]})
        packets.append({**packets[0], "choices": [], "usage": {
            "prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}})
        # EOF without [DONE] is intentionally legal only if choice termination
        # was already observed. An empty chunk/usage packet alone is not proof.
        body = "".join("data: " + json.dumps(item) + "\n\n" for item in packets)
        return httpx.Response(200, text=body, headers={"Content-Type": "text/event-stream"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        adapter = ChatOpenAIWithReasoning(model="deepseek-v4-pro", api_key="offline",
                  base_url="https://example.invalid/v1", http_client=transport,
                  stream_usage=True, max_retries=0)
        adapter._vibe_provider = "deepseek"
        client = _client(adapter)
        if terminal:
            result = client.stream_chat([{"role": "user", "content": "Calculate"}])
            assert result.has_tool_calls is tool_call
            assert result.usage_metadata["total_tokens"] == 30
        else:
            with pytest.raises(ProviderStreamError, match="terminal finish reason") as error:
                client.stream_chat([{"role": "user", "content": "Calculate"}])
            assert error.value.retryable
            assert error.value.usage_metadata["total_tokens"] == 30
    assert len(requests) == 1  # No hidden invoke replay after emitted chunks.


@pytest.mark.parametrize("status", ["completed", "incomplete"])
def test_responses_terminal_status_remains_valid(status):
    """Responses has terminal status rather than Chat Completions finish_reason."""
    chunk = _FakeChunk(content="Answer")
    chunk.response_metadata = {"status": status}
    fake = _FakeStreamingLLM([chunk])
    fake._llm_type = "openai-chat"
    assert _client(fake).stream_chat([{"role": "user", "content": "Hi"}]).content == "Answer"


def test_cancelled_openai_stream_does_not_require_terminal_metadata():
    chunk = _FakeChunk(content="Partial")
    chunk.response_metadata = {}
    fake = _FakeStreamingLLM([chunk])
    fake._llm_type = "openai-chat"
    response = _client(fake).stream_chat(
        [{"role": "user", "content": "Hi"}], should_cancel=lambda: True)
    assert response.content == ""
    assert not fake.invoke_called
