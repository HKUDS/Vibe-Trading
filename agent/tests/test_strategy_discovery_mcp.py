"""Frozen-contract tests for Strategy Discovery tools over MCP — issue #969.

AC1 (no phantom tools): ``list_strategies`` / ``query_strategies`` /
``get_strategy_evidence`` / ``refresh_strategy_evidence`` must be registered
on the FastMCP server and each wrapper must delegate to
``registry.execute(<own name>, <args>)`` — never the generic "Tool not
found" path when the facade layer can answer, and never a crash when the
registry is missing or broken (actionable JSON instead).

Follows the ``test_qveris_mcp.py`` fixture pattern: a fresh/monkeypatched
``mcp_server._registry`` per test. No network: delegation is verified against
recording fake registries; the real store/facade are never constructed.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import mcp_server
from src.agent.tools import ToolRegistry

SD_TOOLS = (
    "list_strategies",
    "query_strategies",
    "get_strategy_evidence",
    "refresh_strategy_evidence",
)


def _unwrapped(name: str):
    """Return the raw callable behind a fastmcp-registered tool, or None."""
    obj = getattr(mcp_server, name, None)
    if obj is None:
        return None
    return getattr(obj, "fn", None) or getattr(obj, "__wrapped__", None) or obj


def _sd_tools_landed() -> bool:
    return all(getattr(mcp_server, name, None) is not None for name in SD_TOOLS)


requires_sd_mcp = pytest.mark.skipif(
    not _sd_tools_landed(),
    reason="waiting on sibling B: mcp_server Strategy Discovery tools not landed yet (issue #969)",
)


@pytest.fixture(autouse=True)
def fresh_mcp_registry():
    """Reset the cached registry so each test rebuilds under its own patch."""
    mcp_server._registry = None
    yield
    mcp_server._registry = None


class _RecordingRegistry:
    """Records execute() calls and returns canned envelopes."""

    def __init__(self, canned='{"status": "ok", "recorded": true}'):
        self.calls = []
        self.canned = canned

    def execute(self, name, params):
        self.calls.append((name, dict(params)))
        return self.canned


@requires_sd_mcp
class TestRegistration:
    def test_all_three_tools_registered_with_descriptions(self) -> None:
        tools = asyncio.run(mcp_server.mcp.list_tools())
        registered = {t.name for t in tools}
        missing = set(SD_TOOLS) - registered
        assert not missing, (
            f"MCP server is missing Strategy Discovery tools: {missing}. "
            "Issue #969 requires all three registered AND callable (AC1)."
        )
        by_name = {t.name: t for t in tools}
        for name in SD_TOOLS:
            description = getattr(by_name[name], "description", "") or ""
            assert description.strip(), f"{name} must carry an MCP description"
            assert callable(_unwrapped(name)), f"mcp_server.{name} is not callable"


@requires_sd_mcp
class TestDelegation:
    @pytest.mark.parametrize(
        "tool_name,args",
        [
            ("list_strategies", {"limit": 7, "offset": 2, "source": "alpha_zoo"}),
            (
                "query_strategies",
                {"regime": "bear_market", "min_trades": 12, "cost_feasible": True},
            ),
            ("get_strategy_evidence", {"strategy_id": "alpha_zoo:a1", "regime": None}),
        ],
    )
    def test_wrapper_delegates_to_registry_execute_with_own_name(
        self, monkeypatch, tool_name, args
    ) -> None:
        recording = _RecordingRegistry()
        monkeypatch.setattr(mcp_server, "_get_registry", lambda: recording)

        fn = _unwrapped(tool_name)
        result = fn(**args)

        assert recording.calls, f"{tool_name} did not call registry.execute"
        called_name, called_params = recording.calls[-1]
        assert (
            called_name == tool_name
        ), f"{tool_name} must delegate under its own name, got {called_name!r}"
        for key, value in args.items():
            if value is None:
                continue
            assert key in called_params and called_params[key] == value, (
                f"{tool_name}: argument {key}={value!r} not forwarded "
                f"(params={called_params!r})"
            )
        assert result == recording.canned

    def test_missing_tool_in_registry_surfaces_json_error_not_crash(
        self, monkeypatch
    ) -> None:
        # A registry that lacks the tool (e.g. facade import failed) must
        # still answer with a parseable error envelope.
        monkeypatch.setattr(mcp_server, "_get_registry", lambda: ToolRegistry())
        fn = _unwrapped("list_strategies")
        result = fn()
        payload = json.loads(result)
        assert payload.get("status") == "error"
        assert payload.get("error")

    def test_broken_registry_yields_actionable_error_not_exception(
        self, monkeypatch
    ) -> None:
        # The exception message is a leak canary: the envelope must be a
        # generic error, never echoing raw exception text (internal paths).
        canary = "internal-detail /etc/shards/leak canary 7f3d"

        def _exploding_registry():
            raise RuntimeError(canary)

        monkeypatch.setattr(mcp_server, "_get_registry", _exploding_registry)
        for name in SD_TOOLS:
            fn = _unwrapped(name)
            if name == "get_strategy_evidence":
                result = fn(strategy_id="alpha_zoo:a1")
            else:
                result = fn()
            payload = json.loads(result)
            assert (
                payload.get("status") == "error" or payload.get("ok") is False
            ), f"{name}: broken registry must produce an error envelope, got {payload!r}"
            error = payload.get("error")
            assert error, f"{name}: error envelope must carry a message"
            assert (
                canary not in error
            ), f"{name}: raw exception text leaked into the envelope: {error!r}"
