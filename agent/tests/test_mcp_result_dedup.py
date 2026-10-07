"""Agent-facing MCP results must not carry the same payload several times."""

from __future__ import annotations

import json
from typing import Any

from fastmcp import Client, FastMCP
from fastmcp.client.client import CallToolResult
from mcp import types as mcp_types

from src.config.schema import MCPServerConfig
from src.tools.mcp import (
    MCPServerAdapter,
    build_mcp_tool_wrappers,
    compact_result_for_agent,
)


def _metrics(count: int) -> dict[str, Any]:
    return {"metrics": [{"name": f"metric_{i:03d}", "value": round(1.23 + i, 2)} for i in range(count)]}


def _tool_for(server: FastMCP, name: str):
    return build_mcp_tool_wrappers(
        "synth",
        MCPServerConfig(command="x", enabled_tools=[name]),
        client_factory=lambda: Client(server),
    )[0]


def _structured_server(count: int) -> FastMCP:
    server = FastMCP("synthetic")

    @server.tool
    def get_metrics() -> dict:
        return _metrics(count)

    return server


def _leaves(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(_leaves(item, f"{path}.{key}" if path else key))
        return out
    if isinstance(value, list):
        out = {}
        for index, item in enumerate(value):
            out.update(_leaves(item, f"{path}[{index}]"))
        return out
    return {path: value}


def test_structured_result_reaches_agent_once() -> None:
    tool = _tool_for(_structured_server(200), "get_metrics")
    raw = tool.execute()
    payload = json.loads(raw)

    assert raw.count("metric_000") == 1
    assert payload["data"] == _metrics(200)
    for redundant in ("structured_content", "content", "text"):
        assert redundant not in payload
    assert payload["status"] == "ok"
    assert payload["server"] == "synth"
    assert payload["remote_tool"] == "get_metrics"
    assert payload["tool"] == tool.name
    # One canonical copy plus a small envelope, not 4x the payload.
    assert len(raw) < len(json.dumps(_metrics(200), separators=(",", ":"))) * 1.25


def test_adapter_call_tool_keeps_every_surface_for_programmatic_callers() -> None:
    server = _structured_server(5)
    adapter = MCPServerAdapter("synth", MCPServerConfig(command="x"), client_factory=lambda: Client(server))
    payload = adapter.call_tool("get_metrics", {})

    assert payload["data"] == _metrics(5)
    assert payload["structured_content"] == _metrics(5)
    assert payload["content"][0]["text"]
    assert payload["text"]


def test_grounding_numeric_leaves_are_still_observable_under_data() -> None:
    payload = json.loads(_tool_for(_structured_server(50), "get_metrics").execute())
    leaves = _leaves(payload)

    assert leaves["data.metrics[0].value"] == 1.23
    assert leaves["data.metrics[49].value"] == 50.23
    assert sum(isinstance(v, (int, float)) for v in leaves.values()) == 50


def test_wrapped_string_tool_result_is_carried_once() -> None:
    server = FastMCP("synthetic")

    @server.tool
    def say() -> str:
        return "plain words"

    raw = _tool_for(server, "say").execute()

    assert json.loads(raw)["data"] == "plain words"
    assert raw.count("plain words") == 1


def _ok(**fields: Any) -> dict[str, Any]:
    return {"status": "ok", "server": "s", "remote_tool": "t", "tool": "t", **fields}


def test_text_only_payload_is_returned_unchanged() -> None:
    payload = _ok(content=[{"type": "text", "text": "hello"}], text="hello")

    assert compact_result_for_agent(payload) is payload


def test_text_only_json_lookalike_without_data_is_not_touched() -> None:
    payload = _ok(content=[{"type": "text", "text": '{"a": 1}'}], text='{"a": 1}')

    assert compact_result_for_agent(payload) == payload


def test_text_only_end_to_end_keeps_content_and_text() -> None:
    fake = CallToolResult(
        content=[mcp_types.TextContent(type="text", text="human readable note")],
        structured_content=None,
        meta=None,
        data=None,
    )
    from src.tools.mcp import _normalize_call_tool_result

    normalized = _normalize_call_tool_result(fake)

    assert compact_result_for_agent(normalized) == normalized
    assert normalized["text"] == "human readable note"


def test_mixed_structured_and_distinct_human_text_keeps_human_text() -> None:
    data = {"a": 1}
    human = {"type": "text", "text": "note for humans"}
    mirror = {"type": "text", "text": json.dumps(data)}
    result = compact_result_for_agent(
        _ok(
            data=data,
            structured_content=data,
            content=[mirror, human],
            text=f"{mirror['text']}\n{human['text']}",
        )
    )

    assert result["data"] == data
    assert result["content"] == [human]
    assert "structured_content" not in result
    assert "text" not in result  # only embedded the mirror + the kept block


def test_data_with_distinct_text_only_keeps_content_and_text() -> None:
    payload = _ok(
        data={"a": 1},
        content=[{"type": "text", "text": "unrelated"}],
        text="unrelated",
    )

    assert compact_result_for_agent(payload) == payload


def test_text_that_is_not_the_derived_join_is_kept() -> None:
    data = {"a": 1}
    result = compact_result_for_agent(
        _ok(data=data, content=[{"type": "text", "text": json.dumps(data)}], text="something else")
    )

    assert "content" not in result
    assert result["text"] == "something else"


def test_distinct_blocks_are_never_deduplicated() -> None:
    data = {"a": 1}
    blocks = [
        {"type": "text", "text": json.dumps(data)},
        {"type": "text", "text": "extra commentary"},
        {"type": "image", "data": "AAAA", "mimeType": "image/png"},
    ]
    result = compact_result_for_agent(
        _ok(
            data=data,
            structured_content=data,
            content=blocks,
            text=f"{blocks[0]['text']}\n{blocks[1]['text']}",
        )
    )

    assert result["data"] == data
    assert result["content"] == blocks[1:]
    assert "structured_content" not in result
    assert "text" not in result  # embedded the removed mirror; remaining blocks keep the rest


def test_block_with_metadata_is_kept() -> None:
    data = {"a": 1}
    block = {"type": "text", "text": json.dumps(data), "annotations": {"audience": ["user"]}}
    result = compact_result_for_agent(_ok(data=data, content=[block]))

    assert result["content"] == [block]


def test_differing_text_and_data_are_both_kept() -> None:
    result = compact_result_for_agent(
        _ok(data={"a": 1}, content=[{"type": "text", "text": json.dumps({"a": 2})}])
    )

    assert result["content"] == [{"type": "text", "text": '{"a": 2}'}]


def test_bool_and_int_are_not_treated_as_equal() -> None:
    result = compact_result_for_agent(_ok(data=True, content=[{"type": "text", "text": "1"}]))

    assert result["content"] == [{"type": "text", "text": "1"}]


def test_wrapped_primitive_result_is_deduplicated_without_losing_value() -> None:
    result = compact_result_for_agent(
        _ok(
            data=8,
            structured_content={"result": 8},
            content=[{"type": "text", "text": "8"}],
            text="8",
        )
    )

    assert result["data"] == 8
    assert "structured_content" not in result
    assert "content" not in result
    assert "text" not in result


def test_structured_content_that_differs_from_data_is_kept() -> None:
    result = compact_result_for_agent(_ok(data={"a": 1}, structured_content={"a": 2}))

    assert result["structured_content"] == {"a": 2}


def test_error_payload_is_returned_unchanged() -> None:
    payload = {
        "status": "error",
        "server": "s",
        "remote_tool": "t",
        "tool": "t",
        "error": "boom",
        "content": [{"type": "text", "text": "boom"}],
        "text": "boom",
    }

    assert compact_result_for_agent(payload) is payload


def test_error_result_end_to_end_keeps_message() -> None:
    server = FastMCP("synthetic")

    @server.tool
    def fail() -> str:
        raise ValueError("synthetic failure")

    payload = json.loads(_tool_for(server, "fail").execute())

    assert payload["status"] == "error"
    assert "synthetic failure" in payload["error"]


def test_compaction_does_not_mutate_the_adapter_payload() -> None:
    data = {"a": 1}
    original = _ok(
        data=data,
        structured_content=data,
        content=[{"type": "text", "text": '{"a": 1}'}],
        text='{"a": 1}',
    )
    snapshot = json.loads(json.dumps(original))

    compact_result_for_agent(original)

    assert original == snapshot


def test_legacy_data_without_structured_content_drops_mirror_text() -> None:
    result = compact_result_for_agent(
        _ok(data={"a": 1}, content=[{"type": "text", "text": '{\n  "a": 1\n}'}], text='{\n  "a": 1\n}')
    )

    assert result["data"] == {"a": 1}
    assert "content" not in result and "text" not in result


def test_hydration_fallback_result_is_reduced_to_one_copy() -> None:
    state: dict[str, Any] = {}
    structured = {"k": 1.5}
    fake = CallToolResult(
        content=[mcp_types.TextContent(type="text", text=json.dumps(structured))],
        structured_content=structured,
        meta=None,
        data=None,
    )
    from src.tools.mcp import _normalize_call_tool_result

    compact = compact_result_for_agent(_normalize_call_tool_result(fake))
    del state

    assert json.dumps(compact).count("1.5") == 1
    assert compact["data"] == structured


def test_call_tool_shape_is_unchanged() -> None:
    server = _structured_server(3)
    adapter = MCPServerAdapter("synth", MCPServerConfig(command="x"), client_factory=lambda: Client(server))
    payload = adapter.call_tool("get_metrics", {}, local_name="synth_get_metrics")
    expected = _metrics(3)

    assert list(payload) == [
        "status", "data", "structured_content", "content", "text", "server", "remote_tool", "tool",
    ]
    assert payload["data"] == expected
    assert payload["structured_content"] == expected
    assert json.loads(payload["content"][0]["text"]) == expected
    assert payload["content"][0]["type"] == "text"
    assert json.loads(payload["text"]) == expected
    assert payload["tool"] == "synth_get_metrics"


def test_structured_only_result_keeps_data_and_envelope() -> None:
    data = {"k": 2.5}
    result = compact_result_for_agent(_ok(data=data, structured_content=data))

    assert result == _ok(data=data)


def test_every_unique_string_survives_compaction() -> None:
    data = {"a": "alpha"}
    blocks = [
        {"type": "text", "text": json.dumps(data)},
        {"type": "text", "text": "unique one", "meta": {"k": "v"}},
        {"type": "text", "text": "unique two"},
    ]
    joined = "\n".join(b["text"] for b in blocks)
    dumped = json.dumps(compact_result_for_agent(_ok(data=data, structured_content=data, content=blocks, text=joined)))

    for needle in ("alpha", "unique one", "unique two", '"k": "v"'):
        assert needle in dumped
