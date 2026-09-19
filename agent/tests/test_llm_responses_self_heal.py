"""A chat-completions refusal that names /v1/responses is healed there (#1473).

OpenAI's gpt-5.6-* reject function tools on ``/v1/chat/completions`` unless
``reasoning_effort`` is 'none' -- the model's own default effort included, so a
plain ``LANGCHAIN_PROVIDER=openai`` setup failed on its first tool call::

    Function tools with reasoning_effort are not supported for gpt-5.6-terra in
    /v1/chat/completions. To use function tools, use /v1/responses or set
    reasoning_effort to 'none'.

The adapter treats that refusal like a rejected ``temperature`` (#1223) or
``stream_options`` (#1224): retry once on ``/v1/responses`` and remember the
model. These tests replay the endpoint's message verbatim through a mock
transport; the live endpoint is the reporter's to confirm.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

import httpx
import pytest

import src.providers.llm as llm_mod
from src.providers.llm import ChatOpenAIWithReasoning, _is_responses_required_error

pytestmark = pytest.mark.skipif(
    ChatOpenAIWithReasoning is None, reason="langchain-openai is not installed"
)

_REFUSAL = (
    "Function tools with reasoning_effort are not supported for {model} in "
    "/v1/chat/completions. To use function tools, use /v1/responses or set "
    "reasoning_effort to 'none'."
)

_TOOL = {
    "type": "function",
    "function": {
        "name": "get_price",
        "description": "Last price of a symbol",
        "parameters": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
}


@pytest.fixture(autouse=True)
def _forget_healed_models() -> Iterator[None]:
    """The memory is process-wide; no test may inherit another's entry."""
    llm_mod._RESPONSES_REQUIRED.clear()
    yield
    llm_mod._RESPONSES_REQUIRED.clear()


def _refusal(model: str) -> httpx.Response:
    return httpx.Response(
        400,
        json={
            "error": {
                "message": _REFUSAL.format(model=model),
                "type": "invalid_request_error",
                "param": "reasoning_effort",
                "code": None,
            }
        },
    )


def _responses_tool_call(model: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "resp_1",
            "object": "response",
            "created_at": 0,
            "model": model,
            "output": [
                {
                    "id": "fc_1",
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "get_price",
                    "arguments": json.dumps({"symbol": "AAPL"}),
                    "status": "completed",
                }
            ],
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
            "usage": {
                "input_tokens": 5,
                "output_tokens": 3,
                "total_tokens": 8,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        },
    )


def _responses_text_stream(model: str) -> httpx.Response:
    completed = {
        "id": "resp_2",
        "object": "response",
        "created_at": 0,
        "model": model,
        "output": [
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "hello", "annotations": []}],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }
    events = [
        {
            "type": "response.output_text.delta",
            "sequence_number": 0,
            "item_id": "msg_1",
            "output_index": 0,
            "content_index": 0,
            "delta": "hel",
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 1,
            "item_id": "msg_1",
            "output_index": 0,
            "content_index": 0,
            "delta": "lo",
        },
        {"type": "response.completed", "sequence_number": 2, "response": completed},
    ]
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def _chat_ok(model: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl_1",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        },
    )


class _Endpoint:
    """Record every request; answer by path."""

    def __init__(self, model: str, *, chat: Any = None, responses: Any = None) -> None:
        self.model = model
        self.chat = chat or (lambda request: _refusal(model))
        self.responses = responses or (lambda request: _responses_tool_call(model))
        self.paths: list[str] = []
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        self.bodies.append(json.loads(request.content))
        if request.url.path == "/v1/chat/completions":
            return self.chat(request)
        if request.url.path == "/v1/responses":
            return self.responses(request)
        raise AssertionError(f"unexpected path {request.url.path}")


def _adapter(client: httpx.Client, model: str, **overrides: Any) -> ChatOpenAIWithReasoning:
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": "sk-test",
        "base_url": "https://api.openai.invalid/v1",
        "http_client": client,
        "use_responses_api": False,
        "max_retries": 0,
        "vibe_provider": "openai",
        "vibe_api_key": "sk-test",
    }
    kwargs.update(overrides)
    return ChatOpenAIWithReasoning(**kwargs)


def test_a_refusal_naming_responses_is_retried_there_with_the_tools() -> None:
    endpoint = _Endpoint("gpt-5.6-terra")
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        llm = _adapter(client, "gpt-5.6-terra").bind_tools([_TOOL])
        message = llm.invoke("price of AAPL?")

    assert endpoint.paths == ["/v1/chat/completions", "/v1/responses"]
    assert [call["name"] for call in message.tool_calls] == ["get_price"]
    assert message.tool_calls[0]["args"] == {"symbol": "AAPL"}
    sent = endpoint.bodies[1]
    assert sent["tools"] == [{"type": "function", **_TOOL["function"]}]
    assert "messages" not in sent and sent["input"], "the Responses request uses `input`"
    assert "reasoning_effort" not in sent, "no effort was configured; none is invented"
    assert "gpt-5.6-terra" in llm_mod._RESPONSES_REQUIRED


def test_the_model_is_remembered_so_the_next_call_skips_the_refusal() -> None:
    endpoint = _Endpoint("gpt-5.6-luna")
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        llm = _adapter(client, "gpt-5.6-luna").bind_tools([_TOOL])
        llm.invoke("first")
        llm.invoke("second")
        again = _adapter(client, "gpt-5.6-luna").bind_tools([_TOOL])
        again.invoke("third, from a fresh adapter in the same process")

    assert endpoint.paths == [
        "/v1/chat/completions",
        "/v1/responses",
        "/v1/responses",
        "/v1/responses",
    ]


def test_a_configured_effort_travels_as_reasoning_effort_on_the_retry() -> None:
    endpoint = _Endpoint("gpt-5.6-terra")
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        llm = _adapter(client, "gpt-5.6-terra", reasoning_effort="high").bind_tools([_TOOL])
        llm.invoke("price?")

    assert endpoint.bodies[0]["reasoning_effort"] == "high"
    assert endpoint.bodies[1]["reasoning"] == {"effort": "high"}
    assert "reasoning_effort" not in endpoint.bodies[1]


def test_the_stream_path_retries_before_any_chunk_was_emitted() -> None:
    endpoint = _Endpoint(
        "gpt-5.6-terra", responses=lambda request: _responses_text_stream("gpt-5.6-terra")
    )
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        llm = _adapter(client, "gpt-5.6-terra").bind_tools([_TOOL])
        text = "".join(chunk.text for chunk in llm.stream("hi"))

    assert text == "hello"
    assert endpoint.paths == ["/v1/chat/completions", "/v1/responses"]
    assert endpoint.bodies[1]["stream"] is True


def test_a_model_whose_chat_endpoint_accepts_tools_is_left_alone() -> None:
    endpoint = _Endpoint("gpt-4.1", chat=lambda request: _chat_ok("gpt-4.1"))
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        llm = _adapter(client, "gpt-4.1", reasoning_effort="high").bind_tools([_TOOL])
        assert llm.invoke("hi").content == "ok"

    assert endpoint.paths == ["/v1/chat/completions"]
    assert llm_mod._RESPONSES_REQUIRED == set()


def test_an_unrelated_400_is_raised_untouched_and_nothing_is_remembered() -> None:
    def unknown_field(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Unrecognized request argument supplied: reasoning_effort",
                    "type": "invalid_request_error",
                    "param": "reasoning_effort",
                }
            },
        )

    endpoint = _Endpoint("house-model", chat=unknown_field)
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        llm = _adapter(client, "house-model", reasoning_effort="high").bind_tools([_TOOL])
        with pytest.raises(Exception, match="Unrecognized request argument"):
            llm.invoke("hi")

    assert endpoint.paths == ["/v1/chat/completions"], "a gateway's unknown-field error is not rerouted"
    assert llm_mod._RESPONSES_REQUIRED == set()


def test_a_refusal_on_the_responses_route_itself_is_not_retried_forever() -> None:
    """If /v1/responses answers with the same text, the error surfaces once."""
    endpoint = _Endpoint("gpt-5.6-terra", responses=lambda request: _refusal("gpt-5.6-terra"))
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        llm = _adapter(client, "gpt-5.6-terra").bind_tools([_TOOL])
        with pytest.raises(Exception, match="not supported"):
            llm.invoke("hi")

    assert endpoint.paths == ["/v1/chat/completions", "/v1/responses"]


def test_an_explicit_responses_route_is_never_rerouted() -> None:
    """Explicit ``LANGCHAIN_USE_RESPONSES_API=true`` owns the transport."""
    endpoint = _Endpoint("gpt-5.6-terra", responses=lambda request: _refusal("gpt-5.6-terra"))
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        llm = _adapter(client, "gpt-5.6-terra", use_responses_api=True, output_version="responses/v1")
        with pytest.raises(Exception, match="not supported"):
            llm.bind_tools([_TOOL]).invoke("hi")

    assert endpoint.paths == ["/v1/responses"]
    assert llm_mod._RESPONSES_REQUIRED == set()


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (_REFUSAL.format(model="gpt-5.6-sol"), True),
        ("Error code: 400 - {'error': {'message': \"" + _REFUSAL.format(model="gpt-5.6-terra") + "\"}}", True),
        ("Unrecognized request argument supplied: reasoning_effort", False),
        ("stream_options is not supported by this endpoint", False),
        ("reasoning_effort: use /v1/responses", False),
        ("", False),
    ],
)
def test_the_matcher_reads_the_endpoints_instruction(message: str, expected: bool) -> None:
    assert _is_responses_required_error(RuntimeError(message)) is expected
