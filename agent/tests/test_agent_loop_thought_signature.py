"""Regression coverage for Gemini thought_signature replay in AgentLoop history."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, convert_to_messages

from src.agent.context import ContextBuilder
from src.agent.loop import _attach_tool_call_thought_signatures
from src.providers.chat import ChatLLM, ToolCallRequest


def _raw_tool_call(
    call_id: str,
    name: str,
    arguments: dict,
    thought_signature: str | None = None,
) -> dict:
    raw = {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }
    if thought_signature:
        raw["extra_content"] = {"thought_signature": thought_signature}
    return raw


def test_dict_history_replay_preserves_thought_signature() -> None:
    message = ContextBuilder.format_assistant_tool_calls(
        [
            ToolCallRequest(
                id="tc_1",
                name="get_price",
                arguments={"symbol": "AAPL"},
                extra_content={"thought_signature": "sig-iteration-1"},
            )
        ],
        content="",
    )

    replayed = convert_to_messages([message])[0]
    raw_tool_call = replayed.additional_kwargs["tool_calls"][0]

    assert message["tool_calls"][0]["extra_content"]["thought_signature"] == "sig-iteration-1"
    assert raw_tool_call["extra_content"]["thought_signature"] == "sig-iteration-1"


def test_multiple_tool_calls_keep_their_own_signatures() -> None:
    message = ContextBuilder.format_assistant_tool_calls(
        [
            ToolCallRequest(
                id="tc_signed_1",
                name="get_price",
                arguments={"symbol": "AAPL"},
                extra_content={"thought_signature": "sig-a"},
            ),
            ToolCallRequest(
                id="tc_unsigned",
                name="get_news",
                arguments={"symbol": "MSFT"},
            ),
            ToolCallRequest(
                id="tc_signed_2",
                name="get_fundamentals",
                arguments={"symbol": "GOOG"},
                extra_content={"thought_signature": "sig-g"},
            ),
        ],
        content="",
    )

    raw_tool_calls = message["additional_kwargs"]["tool_calls"]

    assert raw_tool_calls[0]["extra_content"]["thought_signature"] == "sig-a"
    assert "extra_content" not in raw_tool_calls[1]
    assert raw_tool_calls[2]["extra_content"]["thought_signature"] == "sig-g"


def test_in_memory_ai_message_path_preserves_thought_signature() -> None:
    ai_message = AIMessage(
        content="",
        tool_calls=[
            {"id": "tc_1", "name": "get_price", "args": {"symbol": "AAPL"}},
        ],
        additional_kwargs={
            "tool_calls": [
                _raw_tool_call(
                    "tc_1",
                    "get_price",
                    {"symbol": "AAPL"},
                    thought_signature="sig-from-ai-message",
                )
            ]
        },
    )

    response = ChatLLM._parse_response(ai_message)
    replay = ContextBuilder.format_assistant_tool_calls(response.tool_calls, content="")

    assert response.tool_calls[0].extra_content["thought_signature"] == "sig-from-ai-message"
    assert replay["additional_kwargs"]["tool_calls"][0]["extra_content"]["thought_signature"] == \
        "sig-from-ai-message"


def test_loop_helper_attaches_thought_signature_to_dict_history() -> None:
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            _raw_tool_call("tc_1", "get_price", {"symbol": "AAPL"}),
            _raw_tool_call("tc_2", "get_news", {"symbol": "MSFT"}),
        ],
    }
    tool_calls = [
        ToolCallRequest(
            id="tc_1",
            name="get_price",
            arguments={"symbol": "AAPL"},
            extra_content={"thought_signature": "sig-only-first"},
        ),
        ToolCallRequest(id="tc_2", name="get_news", arguments={"symbol": "MSFT"}),
    ]

    attached = _attach_tool_call_thought_signatures(message, tool_calls)
    raw_tool_calls = attached["additional_kwargs"]["tool_calls"]

    assert raw_tool_calls[0]["extra_content"]["thought_signature"] == "sig-only-first"
    assert "extra_content" not in raw_tool_calls[1]


def test_unsigned_tool_calls_do_not_emit_signature_metadata() -> None:
    message = ContextBuilder.format_assistant_tool_calls(
        [ToolCallRequest(id="tc_1", name="get_price", arguments={"symbol": "AAPL"})],
        content="",
    )

    assert "additional_kwargs" not in message
    assert "extra_content" not in message["tool_calls"][0]
