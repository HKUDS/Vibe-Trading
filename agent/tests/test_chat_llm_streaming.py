"""ChatLLM streaming liveness and error semantics."""

from __future__ import annotations

from tests.provider_helpers import chat_with_adapter

import os
import threading
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessageChunk

from src.providers.response import parse_response
from src.providers.response import ProviderStreamError


class _FakeStreamingLLM:
    def __init__(self, chunks: list[AIMessageChunk] | None = None, exc: Exception | None = None) -> None:
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
        return AIMessageChunk(content="fallback")


def _client(fake_llm: _FakeStreamingLLM):
    return chat_with_adapter(fake_llm, model="deepseek-v4-pro")


def test_reasoning_only_chunks_emit_progress_without_final_answer_text() -> None:
    fake = _FakeStreamingLLM([
        AIMessageChunk(content="", additional_kwargs={"reasoning_content": "thinking "}),
        AIMessageChunk(content="", additional_kwargs={"reasoning_content": "more"}),
        AIMessageChunk(content="final"),
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

    response = parse_response(AIMessageChunk(content=content))

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

    response = parse_response(AIMessageChunk(content=content))

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
    fake = _FakeStreamingLLM([AIMessageChunk(content=content)])
    text_chunks: list[str] = []

    response = _client(fake).stream_chat(
        [{"role": "user", "content": "hi"}],
        on_text_chunk=text_chunks.append,
    )

    assert text_chunks == []
    assert response.content == ""
    assert response.tool_calls[0].name == "bash"


@pytest.mark.parametrize("streaming", [False, True], ids=["complete", "split-stream"])
def test_captured_dsml_calls_normalize_without_streaming_markup(streaming: bool) -> None:
    """Replay the Ark capture's wrapper, tag spacing, and string attribute."""
    content = (
        '<｜｜DSML｜｜ calls>\n'
        '<｜｜DSML｜｜ invoke name="bash">\n'
        '<｜｜DSML｜｜ parameter name="command" string="true">pwd</｜｜DSML｜｜ parameter>\n'
        '</｜｜DSML｜｜ invoke>\n'
        '</｜｜DSML｜｜ calls>'
    )
    text_chunks: list[str] = []
    if streaming:
        fake = _FakeStreamingLLM([AIMessageChunk(content=piece) for piece in [
            content[:2], content[2:13], content[13:16], content[16:],
        ]])
        response = _client(fake).stream_chat(
            [{"role": "user", "content": "hi"}], on_text_chunk=text_chunks.append
        )
    else:
        response = parse_response(AIMessageChunk(content=content))

    assert text_chunks == []
    assert response.content == ""
    assert response.finish_reason == "tool_calls"
    assert [(call.name, call.arguments) for call in response.tool_calls] == [
        ("bash", {"command": "pwd"}),
    ]


def test_ascii_dsml_preserves_typed_json_and_explicit_strings() -> None:
    """Decode typed arguments and keep JSON-looking strings as text."""
    content = (
        '< || DSML || tool_calls >'
        '<||DSML||invoke name="probe">'
        '<||DSML||parameter name="options" string="false">{"n":2,"flags":[true,null]}</||DSML||parameter>'
        '<||DSML||parameter name="label" string="true">false</||DSML||parameter>'
        '</||DSML||invoke></ || DSML || tool_calls >'
    )
    response = parse_response(AIMessageChunk(content=content))

    assert response.tool_calls[0].arguments == {
        "options": {"n": 2, "flags": [True, None]},
        "label": "false",
    }


_DSML_TEST_INVOKE = (
    '<||DSML||invoke name="probe">'
    '<||DSML||parameter name="text" string="true">ok</||DSML||parameter>'
    '</||DSML||invoke>'
)


@pytest.mark.parametrize(
    "damaged_tail",
    [
        '<||DSML||invoke name="probe">',
        '<||DSML||invoke name="probe"><||DSML||parameter name="text">missing close</||DSML||invoke>',
        '<||DSML||invoke name="probe" name="other"></||DSML||invoke>',
        '<||DSML||invoke name="probe" broken></||DSML||invoke>',
        '<||DSML||invoke name="probe"><||DSML||parameter name="text" string="false">[</||DSML||parameter></||DSML||invoke>',
        'unexpected prose inside the wrapper',
        '</||DSML||tool_calls><||DSML||calls>',
    ],
    ids=["invoke", "parameter", "duplicate-attribute", "bad-attribute", "invalid-json", "stray-text", "mismatched-wrapper"],
)
def test_malformed_dsml_never_returns_a_valid_prefix_call(damaged_tail: str) -> None:
    """Reject the entire payload even when an earlier invoke was complete."""
    content = '<||DSML||tool_calls>' + _DSML_TEST_INVOKE + damaged_tail + '</||DSML||tool_calls>'

    response = parse_response(AIMessageChunk(content=content))

    assert response.tool_calls == []
    assert response.content == content


def test_anthropic_content_blocks_stream_with_native_tool_call() -> None:
    chunk = AIMessageChunk(content="")
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
        AIMessageChunk(content="a"),
        AIMessageChunk(content="b"),
        AIMessageChunk(content="c"),
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
    fake = _FakeStreamingLLM([AIMessageChunk(content="x"), AIMessageChunk(content="y")])
    seen: list[str] = []

    response = _client(fake).stream_chat(
        [{"role": "user", "content": "hi"}],
        on_text_chunk=seen.append,
    )

    assert seen == ["x", "y"]
    assert response.content == "xy"


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_stream_failure_is_redacted_without_silent_fallback(error_type):
    """Ordinary stream errors, including ValueError, must not trigger invoke."""
    fake = _FakeStreamingLLM(exc=error_type("bad key sk-live-secret-123456"))
    with patch.dict(os.environ, {
        "LANGCHAIN_PROVIDER": "deepseek", "LANGCHAIN_MODEL_NAME": "deepseek-v4-pro",
        "DEEPSEEK_API_KEY": "sk-live-secret-123456",
    }, clear=True):
        with pytest.raises(ProviderStreamError) as caught:
            _client(fake).stream_chat([{"role": "user", "content": "hi"}])

    message = str(caught.value)
    assert "provider=deepseek" in message and "model=deepseek-v4-pro" in message
    assert "sk-live-secret-123456" not in message and "[redacted]" in message
    assert not fake.invoke_called


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


@pytest.mark.parametrize("reason,content,filtered", [
    ("content_filter", "", True), ("stop", "text", False),
])
def test_content_filter_flag_follows_finish_reason(reason, content, filtered):
    response = parse_response(
        AIMessageChunk(content=content, response_metadata={"finish_reason": reason})
    )
    assert response.content == content
    assert response.finish_reason == reason
    assert response.content_filter_triggered is filtered


@pytest.mark.parametrize("error", [None, ValueError("No generation chunks were returned")],
                         ids=["clean-eof", "langchain-empty-stream"])
def test_empty_stream_falls_back_to_invoke(error):
    """Both empty-SSE forms use the same non-streaming fallback (#758)."""
    fake = _FakeStreamingLLM(exc=error)
    response = _client(fake).stream_chat([{"role": "user", "content": "hi"}])
    assert fake.invoke_called
    assert response.content == "fallback"


@pytest.mark.parametrize("llm_type", [None, "openai-chat"])
def test_cancelled_empty_stream_needs_no_terminal_metadata_or_fallback(llm_type):
    fake = _FakeStreamingLLM([AIMessageChunk(content="ignored")])
    fake._llm_type = llm_type
    response = _client(fake).stream_chat(
        [{"role": "user", "content": "hi"}], should_cancel=lambda: True
    )
    assert not fake.invoke_called
    assert response.content == "" and not response.tool_calls


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


@pytest.mark.parametrize("delay,stalls", [(0.05, False), (0.6, True)], ids=["flowing", "stalled"])
def test_idle_budget_preserves_delivered_text_without_replaying(delay, stalls):
    import time

    class Delayed(_FakeStreamingLLM):
        def stream(self, messages, config=None):
            yield AIMessageChunk(content="first")
            time.sleep(delay)
            yield AIMessageChunk(content="second")

    fake = Delayed()
    client = _client(fake)
    seen = []
    if stalls:
        with pytest.raises(ProviderStreamError, match="idle timeout") as caught:
            client.stream_chat([], idle_timeout_s=0.2, on_text_chunk=seen.append)
        assert caught.value.retryable
        assert seen == ["first"]
    else:
        response = client.stream_chat([], idle_timeout_s=0.2, on_text_chunk=seen.append)
        assert response.content == "firstsecond"
        assert seen == ["first", "second"]
    assert not fake.invoke_called


def test_only_explicit_provider_waiting_reaches_activity_callback():
    waiting = []
    response = _client(_FakeStreamingLLM([
        AIMessageChunk(content=""),
        AIMessageChunk(content="", additional_kwargs={"provider_waiting": True}),
        AIMessageChunk(content="final"),
    ])).stream_chat([{"role": "user", "content": "q"}], on_waiting_chunk=lambda: waiting.append(True))
    assert waiting == [True]
    assert response.content == "final"


@pytest.mark.parametrize("stop", ["node_deadline", "turn_cancel"])
@pytest.mark.parametrize("status", [429, 500])
def test_sdk_retry_wait_ends_with_supervised_stream(stop, status):
    """Use SDK attempts on the wire to detect retries after the caller stops.

    Args:
        stop: Signal that stops the caller while the SDK is backing off.
        status: HTTP response status that triggers the SDK retry.
    """
    import time

    import httpx

    from src.providers.adapters.openai import ChatOpenAIWithReasoning
    from src.swarm.node import NodeModel, NodeStop

    attempts = []
    workers = []
    first_attempt = threading.Event()
    cancel = threading.Event()
    retry_after = 0.5

    def respond(request):
        attempts.append(time.monotonic() - started)
        workers.append(threading.current_thread())
        first_attempt.set()
        return httpx.Response(status, headers={"retry-after": str(retry_after)})

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        adapter = ChatOpenAIWithReasoning(
            model="gpt-test", api_key="offline", base_url="https://example.invalid/v1",
            http_client=transport, max_retries=2,
        )
        client = _client(adapter)
        messages = [{"role": "user", "content": "Hi"}]

        def cancel_turn():
            if first_attempt.wait(2):
                time.sleep(0.05)
                cancel.set()

        started = time.monotonic()
        if stop == "node_deadline":
            node_stop = NodeStop(None, 0.2)
            model = NodeModel(client, node_stop, lambda *args: None, None)
            try:
                model.stream_chat(messages, timeout=None, idle_timeout_s=None,
                                  on_text_chunk=lambda _: None, should_cancel=node_stop.is_set)
            except ProviderStreamError as error:
                assert "timeout" in str(error)
            assert node_stop.expired
        else:
            canceller = threading.Thread(target=cancel_turn)
            canceller.start()
            try:
                assert not client.stream_chat(messages, should_cancel=cancel.is_set).content
            finally:
                canceller.join()
        caller_elapsed = time.monotonic() - started
        assert workers
        workers[0].join(2)
        worker_elapsed = time.monotonic() - started

    print(f"{stop} HTTP {status}: caller={caller_elapsed:.3f}s worker={worker_elapsed:.3f}s "
          f"attempts={[round(offset, 3) for offset in attempts]}")
    assert caller_elapsed < retry_after
    assert len(attempts) == 1
    assert not workers[0].is_alive()
    assert worker_elapsed < retry_after


@pytest.mark.parametrize("stream", [False, True])
def test_sdk_retry_coverage_is_preserved(stream):
    """Check two consecutive retries, including 409 and an explicit retry header.

    Args:
        stream: Whether the request uses the supervised stream or plain chat.
    """
    import json

    import httpx

    from src.providers.adapters.openai import ChatOpenAIWithReasoning

    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(409, headers={"retry-after-ms": "1"})
        if len(requests) == 2:
            return httpx.Response(400, headers={"x-should-retry": "true", "retry-after-ms": "1"})
        choice = {"index": 0, "finish_reason": "stop"}
        packet = {"id": "offline", "created": 0, "model": "gpt-test", "choices": [choice]}
        if stream:
            choice["delta"] = {"content": "hello"}
            packet["object"] = "chat.completion.chunk"
            return httpx.Response(200, text=f"data: {json.dumps(packet)}\n\ndata: [DONE]\n\n",
                                  headers={"content-type": "text/event-stream"})
        choice["message"] = {"role": "assistant", "content": "hello"}
        packet["object"] = "chat.completion"
        return httpx.Response(200, json=packet)

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        adapter = ChatOpenAIWithReasoning(
            model="gpt-test", api_key="offline", base_url="https://example.invalid/v1",
            http_client=transport, max_retries=2,
        )
        client = _client(adapter)
        request = client.stream_chat if stream else client.chat
        assert request([{"role": "user", "content": "Hi"}], timeout=2).content == "hello"

    assert len(requests) == 3


@pytest.mark.parametrize("adapter_kind", ["compatible", "native"])
@pytest.mark.parametrize("terminal", [True, False])
@pytest.mark.parametrize("tool_call", [True, False])
def test_actual_chat_stream_requires_terminal_metadata(terminal, tool_call, adapter_kind):
    """Replay a clean EOF through the real SDK; truncated JSON is not a call."""
    import json
    import httpx
    from src.providers.adapters.openai import ChatOpenAIWithReasoning

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
        adapter_class = (ChatOpenAIWithReasoning if adapter_kind == "compatible"
                         else pytest.importorskip("langchain_deepseek").ChatDeepSeek)
        adapter = adapter_class(model="deepseek-v4-pro", api_key="offline",
                  base_url="https://example.invalid/v1", http_client=transport,
                  stream_usage=True, max_retries=0)
        if adapter_kind == "compatible":
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
    """Keep the distinction between completed and incomplete Responses status.

    Args:
        status: Terminal status reported without a finish reason.
    """
    chunk = AIMessageChunk(content="Answer")
    chunk.response_metadata = {"status": status}
    fake = _FakeStreamingLLM([chunk])
    fake._llm_type = "openai-chat"
    result = _client(fake).stream_chat([{"role": "user", "content": "Hi"}])
    assert result.content == "Answer"
    assert result.finish_reason == ("incomplete" if status == "incomplete" else "stop")


@pytest.mark.parametrize("metadata,args,valid", [
    ({"finish_reason": "tool_calls"}, '{"path":"a.txt"}', True),
    ({"finish_reason": "length"}, '{"path":"a.txt"}', False),
    ({"stop_reason": "max_tokens"}, '{"path":"a.txt"}', False),
    ({"finish_reason": "max_output_tokens"}, '{"path":"a.txt"}', False),
    ({"status": "incomplete"}, '{"path":"a.txt"}', False),
    ({"finish_reason": "tool_calls"}, '{"path":"a.txt', False),
    ({"finish_reason": "tool_calls"}, 'invalid-json', False),
])
def test_only_complete_tool_arguments_can_execute(metadata, args, valid):
    """Require both a complete response and valid JSON for tool execution.

    Args:
        metadata: Finish and status metadata reported by the adapter.
        args: Raw tool arguments received over the stream.
        valid: Whether the parser should accept the tool call.
    """
    chunk = AIMessageChunk(content="", response_metadata=metadata, tool_call_chunks=[
        {"id": "call-1", "index": 0, "name": "write_file", "args": args},
    ])
    if valid:
        assert parse_response(chunk).tool_calls[0].arguments == {"path": "a.txt"}
    else:
        with pytest.raises(ValueError, match="tool.call"):
            parse_response(chunk)
    cancelled = parse_response(chunk, cancelled=True)
    assert not cancelled.has_tool_calls and cancelled.finish_reason == "stop"


@pytest.mark.parametrize("cancel", [False, True])
def test_empty_stream_fallback_keeps_cancellation_and_timeout(cancel):
    release, stopped = threading.Event(), threading.Event()
    fake = _FakeStreamingLLM()

    def invoke(*args, **kwargs):
        fake.invoke_called = True
        if cancel:
            stopped.set()
        release.wait(2)
        return AIMessageChunk(content="late fallback")

    fake.invoke = invoke
    text = []
    try:
        if cancel:
            response = _client(fake).stream_chat([], should_cancel=stopped.is_set, on_text_chunk=text.append)
            assert not response.content and not response.tool_calls
        else:
            with pytest.raises(ProviderStreamError, match="idle timeout"):
                _client(fake).stream_chat([], idle_timeout_s=0.05, on_text_chunk=text.append)
        assert fake.invoke_called and not text
    finally:
        release.set()
