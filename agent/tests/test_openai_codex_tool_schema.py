"""Codex tool schemas are sent non-strict so optional arguments can be omitted."""

from __future__ import annotations

import copy
import json

from src.providers.openai_codex import (
    OpenAICodexLLM,
    _convert_tools,
    _events_from_lines,
    _message_chunks_from_events,
)

TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_record",
        "description": "Read one record.",
        "parameters": {
            "type": "object",
            "properties": {
                "record": {"type": "string", "description": "Required record name."},
                "snapshot_id": {
                    "type": "string",
                    "description": "Optional id; omit for the latest.",
                },
                "no_cache": {"type": "boolean", "default": False},
            },
            "required": ["record"],
        },
    },
}


def _calls(arguments: str) -> list[dict]:
    lines = [
        'data: {"type":"response.output_item.added","item":{"type":"function_call","call_id":"c1","id":"fc_1","name":"lookup_record","arguments":""}}',
        "",
        "data: "
        + '{"type":"response.function_call_arguments.delta","call_id":"c1","delta":'
        + json.dumps(arguments)
        + "}",
        "",
        'data: {"type":"response.output_item.done","item":{"type":"function_call","call_id":"c1"}}',
        "",
        "data: [DONE]",
        "",
    ]
    return [
        c
        for chunk in _message_chunks_from_events(_events_from_lines(lines))
        for c in chunk.tool_calls
    ]


def test_converted_tool_is_explicitly_non_strict_and_keeps_the_schema():
    original = copy.deepcopy(TOOL)

    [converted] = _convert_tools([TOOL])

    assert converted["strict"] is False
    assert converted["type"] == "function"
    assert converted["name"] == "lookup_record"
    assert converted["description"] == "Read one record."
    assert converted["parameters"] == original["function"]["parameters"]
    assert converted["parameters"]["required"] == ["record"]
    assert TOOL == original


def test_every_tool_in_the_request_body_is_non_strict():
    bare = {
        "name": "ping",
        "description": "",
        "parameters": {"type": "object", "properties": {}},
    }
    body = (
        OpenAICodexLLM(model="openai-codex/gpt-6-sol")
        .bind_tools([TOOL, bare])
        ._body([{"role": "user", "content": "hi"}], stream=True)
    )

    assert [t["name"] for t in body["tools"]] == ["lookup_record", "ping"]
    assert all(t["strict"] is False for t in body["tools"])


def test_optional_arguments_can_be_omitted_and_required_ones_still_arrive():
    [omitted] = _calls('{"record":"orders"}')
    [filled] = _calls('{"record":"orders","snapshot_id":"abc","no_cache":true}')

    assert omitted["args"] == {"record": "orders"}
    assert "snapshot_id" not in omitted["args"]
    assert filled["args"] == {
        "record": "orders",
        "snapshot_id": "abc",
        "no_cache": True,
    }
