"""MCP list/dict parameters must tolerate JSON-string arguments (issue #987).

FastMCP publishes optional list/dict parameters as ``anyOf`` schemas, and some
MCP clients (observed with Claude Desktop / Claude Code) do not surface ``anyOf``
to the model as a concrete type — the model then serializes the argument as a
JSON string (``'["us"]'``). Strict pydantic validation used to reject that string
before the tool body ran::

    1 validation error for call[run_shadow_backtest]
    markets
      Input should be a valid list [type=list_type, input_value='["us"]', ...]

Every list/dict MCP parameter now carries a ``BeforeValidator``
(``_coerce_json_string``) that decodes such a string before type checking. The
published JSON schema is deliberately unchanged, so well-behaved clients that
send real arrays/objects are unaffected.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

# (tool, param) pairs that are list/dict-typed in agent/mcp_server.py.
LIST_DICT_PARAMS = {
    "start_research_goal": ("criteria",),
    "add_goal_evidence": (
        "symbol_universe",
        "benchmark",
        "assumptions",
        "contradicts_claim_ids",
    ),
    "update_research_goal_status": ("audit",),
    "analyze_options_payoff": ("legs", "scenario_iv_values"),
    "run_swarm": ("variables",),
    "get_market_data": ("codes",),
    "get_fund_flow": ("codes",),
    "get_stock_profile": ("sections",),
    "run_shadow_backtest": ("markets",),
}


@pytest.fixture(scope="module")
def mcp_server():
    """Import agent/mcp_server.py without executing main()."""
    agent_dir = Path(__file__).resolve().parent.parent
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    return importlib.import_module("mcp_server")


@pytest.fixture(scope="module")
def tool_parameters(mcp_server) -> dict:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    return {t.name: t.parameters for t in tools}


def _declares_container(schema: dict) -> bool:
    """True when a property schema declares array/object, directly or via anyOf."""

    def _is_container(node: dict) -> bool:
        return isinstance(node, dict) and node.get("type") in ("array", "object")

    return _is_container(schema) or any(
        _is_container(branch) for branch in schema.get("anyOf", [])
    )


def _text(result) -> str:
    content = getattr(result, "content", None) or []
    return content[0].text if content else str(result)


# ---------------------------------------------------------------------------
# Schema guard — the fix must not regress these to the client-visible {} shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", sorted(LIST_DICT_PARAMS))
def test_list_dict_params_keep_a_typed_schema(tool, tool_parameters) -> None:
    props = tool_parameters[tool].get("properties", {})
    for param in LIST_DICT_PARAMS[tool]:
        assert param in props, f"{tool}.{param} missing from the input schema"
        assert props[param] != {}, f"{tool}.{param} regressed to an empty schema"
        assert _declares_container(props[param]), (
            f"{tool}.{param} lost its array/object type: {props[param]}"
        )


# ---------------------------------------------------------------------------
# Coercion helper unit behaviour
# ---------------------------------------------------------------------------


def test_coerce_json_string_decodes_arrays_and_objects(mcp_server) -> None:
    coerce = mcp_server._coerce_json_string
    assert coerce('["us", "hk"]') == ["us", "hk"]
    assert coerce('{"target": "AAPL.US"}') == {"target": "AAPL.US"}
    assert coerce("  [1, 2]  ") == [1, 2]


def test_coerce_json_string_passes_through_everything_else(mcp_server) -> None:
    coerce = mcp_server._coerce_json_string
    # Real containers, None and numbers are untouched.
    assert coerce(["us"]) == ["us"]
    assert coerce({"a": 1}) == {"a": 1}
    assert coerce(None) is None
    assert coerce(42) == 42
    # Non-JSON strings pass through so pydantic raises its normal type error.
    assert coerce("us") == "us"
    assert coerce("not json") == "not json"


# ---------------------------------------------------------------------------
# End-to-end through fastmcp.call_tool (the real validation path)
# ---------------------------------------------------------------------------


def test_optional_string_list_is_coerced(mcp_server, tmp_path, monkeypatch) -> None:
    """run_shadow_backtest.markets as a JSON string must not fail validation."""
    from src.goal import GoalStore

    monkeypatch.setattr(mcp_server, "_goal_store", GoalStore(db_path=tmp_path / "g.db"))
    monkeypatch.setattr(mcp_server, "_mcp_session_id", None)

    result = asyncio.run(
        mcp_server.mcp.call_tool(
            "start_research_goal",
            {"objective": "probe #987", "criteria": '["c1", "c2"]'},
        )
    )
    text = _text(result)
    assert '"status": "ok"' in text
    assert "c1" in text and "c2" in text


def test_required_dict_list_is_coerced(mcp_server) -> None:
    """analyze_options_payoff.legs (required list[dict]) as a JSON string."""
    result = asyncio.run(
        mcp_server.mcp.call_tool(
            "analyze_options_payoff",
            {
                "legs": '[{"option_type": "call", "strike": 100, "qty": 1, "premium": 5.0}]',
                "entry_spot": 100.0,
                "expiry_days": 30.0,
            },
        )
    )
    text = _text(result)
    assert '"status": "ok"' in text
    assert "list_type" not in text


def test_real_containers_still_work(mcp_server, tmp_path, monkeypatch) -> None:
    """Well-behaved clients sending real arrays/objects are unaffected."""
    from src.goal import GoalStore

    monkeypatch.setattr(mcp_server, "_goal_store", GoalStore(db_path=tmp_path / "g.db"))
    monkeypatch.setattr(mcp_server, "_mcp_session_id", None)

    result = asyncio.run(
        mcp_server.mcp.call_tool(
            "start_research_goal",
            {"objective": "probe #987 real list", "criteria": ["c1", "c2"]},
        )
    )
    text = _text(result)
    assert '"status": "ok"' in text
    assert "c1" in text and "c2" in text


def test_non_json_string_still_fails_cleanly(mcp_server) -> None:
    """A non-JSON string is passed through and rejected, not silently coerced."""
    try:
        result = asyncio.run(
            mcp_server.mcp.call_tool(
                "analyze_options_payoff",
                {
                    "legs": "definitely-not-json",
                    "entry_spot": 100.0,
                    "expiry_days": 30.0,
                },
            )
        )
    except Exception as exc:  # noqa: BLE001 - fastmcp surfaces validation errors
        assert "list_type" in str(exc) or "valid list" in str(exc)
        return
    # If this fastmcp version returns an error envelope instead of raising,
    # it must still be a failure, not a coerced success.
    assert getattr(result, "isError", False) or '"status": "error"' in _text(result)


# ---------------------------------------------------------------------------
# Mirrored tools (issue #987, second half)
#
# prediction_market / research_papers / etf_holdings / get_institutional_holdings
# are registered with the tool class' own JSON Schema and have no Python
# signature, so fastmcp never validates their arguments and the BeforeValidator
# above cannot be attached. A JSON-string argument therefore reached the tool as
# a str instead of being rejected. _mirrored_call_params decodes off the
# declared type instead, which covers these and any mirrored tool added later.
# ---------------------------------------------------------------------------

_ARRAY = {"type": "array", "items": {"type": "string"}}
_OBJECT = {"type": "object"}
_STRING = {"type": "string"}
_OPTIONAL_ARRAY = {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]}

_MIRRORED_SCHEMA = {
    "type": "object",
    "properties": {
        "ids": _ARRAY,
        "categories": _ARRAY,
        "paper_ids": _ARRAY,
        "filters": _OBJECT,
        "sections": _OPTIONAL_ARRAY,
        "mode": _STRING,
    },
}


@pytest.mark.parametrize(
    "param,sent,expected",
    [
        ("ids", '["12345", "67890"]', ["12345", "67890"]),
        ("categories", '["q-fin.PM"]', ["q-fin.PM"]),
        ("paper_ids", '["2401.00001"]', ["2401.00001"]),
        ("sections", '["profile"]', ["profile"]),
        ("filters", '{"market": "us"}', {"market": "us"}),
        # Already-correct containers pass through untouched.
        ("ids", ["12345"], ["12345"]),
        # A declared string is never JSON-decoded, even when it looks like one.
        ("mode", '["not", "a", "list"]', '["not", "a", "list"]'),
        # A non-JSON string on a container parameter is left for the tool to
        # reject, rather than being mangled here.
        ("ids", "not-json", "not-json"),
    ],
    ids=[
        "ids", "categories", "paper_ids", "sections", "filters",
        "real_list_untouched", "string_param_untouched", "non_json_passthrough",
    ],
)
def test_mirrored_call_params_decodes_json_container_strings(
    mcp_server, param, sent, expected,
) -> None:
    out = mcp_server._mirrored_call_params(_MIRRORED_SCHEMA, {param: sent})
    assert out == {param: expected}


def test_mirrored_call_params_still_drops_nulls_and_undeclared(mcp_server) -> None:
    """The decode must not cost the filtering the function already did."""
    out = mcp_server._mirrored_call_params(
        _MIRRORED_SCHEMA, {"ids": '["1"]', "mode": None, "not_declared": '["x"]'},
    )
    assert out == {"ids": ["1"]}


def test_live_mirrored_tools_declare_the_array_params_this_covers(mcp_server) -> None:
    """Pin that the three parameters #993 missed are really array-typed.

    If a tool renames or retypes them the coercion silently stops applying, so
    this reads the live schema rather than trusting the list above.
    """
    tools = asyncio.run(mcp_server.mcp.list_tools())
    by_name = {t.name: t for t in tools}
    for tool_name, params in (
        ("prediction_market", ("ids",)),
        ("research_papers", ("categories", "paper_ids")),
    ):
        assert tool_name in by_name, f"{tool_name} is not on the MCP surface"
        properties = by_name[tool_name].parameters.get("properties") or {}
        for param in params:
            assert param in properties, f"{tool_name}.{param} is gone"
            assert mcp_server._declares_json_container(properties[param]), (
                f"{tool_name}.{param} is no longer a JSON container"
            )
