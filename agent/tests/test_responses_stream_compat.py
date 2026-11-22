"""Regression tests for OpenAI-compatible Responses event streams."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any, Iterator

import pytest
from langchain_core.messages import HumanMessage

from src.providers.adapters.openai import ChatOpenAIWithReasoning


class _MappingResponses:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    @contextmanager
    def create(self, **kwargs: Any) -> Iterator[Iterator[dict[str, Any]]]:
        yield iter(self._events)


class _MappingRootClient:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.responses = _MappingResponses(events)


class _MappingAsyncStream:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    async def __aenter__(self) -> "_MappingAsyncStream":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def __aiter__(self) -> Any:
        return self._iterate()

    async def _iterate(self) -> Any:
        for event in self._events:
            yield event


class _MappingAsyncResponses:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    async def create(self, **kwargs: Any) -> _MappingAsyncStream:
        return _MappingAsyncStream(self._events)


class _MappingAsyncRootClient:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.responses = _MappingAsyncResponses(events)


def _text_delta_event() -> dict[str, Any]:
    return {
        "type": "response.output_text.delta",
        "delta": "hello",
        "item_id": "msg_1",
        "output_index": 0,
        "content_index": 0,
    }


@pytest.mark.skipif(
    ChatOpenAIWithReasoning is None,
    reason="langchain-openai is not installed",
)
def test_responses_stream_accepts_mapping_events() -> None:
    """OpenAI-compatible gateways may yield dicts instead of SDK event objects."""
    events = [_text_delta_event()]
    llm = ChatOpenAIWithReasoning(
        model="gateway-reasoning-model",
        api_key="sk-test",
        use_responses_api=True,
    )
    llm.root_client = _MappingRootClient(events)
    # Keep this test focused on stream-event compatibility rather than request
    # serialization, which is exercised by the provider payload tests.
    llm._get_request_payload = lambda *args, **kwargs: {
        "model": "gateway-reasoning-model",
        "input": [{"role": "user", "content": "hello"}],
        "stream": True,
    }

    chunks = list(llm.stream("hello"))

    assert "".join(chunk.text for chunk in chunks) == "hello"


@pytest.mark.skipif(
    ChatOpenAIWithReasoning is None,
    reason="langchain-openai is not installed",
)
def test_async_responses_stream_accepts_mapping_events() -> None:
    """The async Responses path must normalize gateway mappings as well."""
    llm = ChatOpenAIWithReasoning(
        model="gateway-reasoning-model",
        api_key="sk-test",
        use_responses_api=True,
    )
    llm.root_async_client = _MappingAsyncRootClient([_text_delta_event()])
    llm._get_request_payload = lambda *args, **kwargs: {
        "model": "gateway-reasoning-model",
        "input": [{"role": "user", "content": "hello"}],
        "stream": True,
    }

    async def collect() -> str:
        chunks = [chunk async for chunk in llm.astream("hello")]
        return "".join(chunk.text for chunk in chunks)

    assert asyncio.run(collect()) == "hello"


@pytest.mark.skipif(
    ChatOpenAIWithReasoning is None,
    reason="langchain-openai is not installed",
)
def test_responses_payload_does_not_assume_chat_messages() -> None:
    """Responses requests use ``input`` and must bypass chat-only rewriting."""
    llm = ChatOpenAIWithReasoning(
        model="gateway-reasoning-model",
        api_key="sk-test",
        use_responses_api=True,
        output_version="responses/v1",
        reasoning={"effort": "high"},
    )

    payload = llm._get_request_payload([HumanMessage(content="hello")])

    assert payload["input"]
    assert payload["reasoning"] == {"effort": "high"}
