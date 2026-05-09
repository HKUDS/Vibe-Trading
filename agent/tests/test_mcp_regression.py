"""Regression tests: existing MCP server mode and no-config behavior.

These tests guard against regressions introduced by the MCP client integration:

1. no-config regression — build_registry() with no agent_config must behave
   identically to before this roadmap: local tools only, no exceptions.

2. MCP server mode regression — importing mcp_server.py must not raise, and
   the FastMCP instance must expose the expected well-known tool names. This
   confirms that the server-side MCP plugin (vibe-trading-mcp) is unaffected
   by the MCP client changes introduced in Phases 1-4.

IMPORTANT notes:
- These tests do NOT start the MCP server process (no mcp.run() call) — they
  only import the module and inspect the registered tool names, which is safe
  and fast.
- Do not add functional tests for individual mcp_server tools here; those
  belong in their own test files.
- TODO(v1): Add a live smoke test that spawns `vibe-trading-mcp` as a stdio
  subprocess once CI has network access and the SSE transport is tested end-
  to-end in Phase 6+.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# No-config regression
# ---------------------------------------------------------------------------


def test_build_registry_without_agent_config_loads_local_tools_only() -> None:
    """build_registry() called with defaults must never raise and must return
    only local tools (no mcp_* names).

    This is the "zero-change" contract for callers that do not opt into MCP
    config yet.
    """
    from src.tools import build_registry

    registry = build_registry()

    names = registry.tool_names
    assert names, "Registry must not be empty when no agent_config is supplied"

    mcp_names = [n for n in names if n.startswith("mcp_")]
    assert mcp_names == [], (
        f"Expected no MCP tools without agent_config, got: {mcp_names}"
    )


def test_build_registry_without_agent_config_does_not_raise() -> None:
    """build_registry() with default arguments must not raise any exception."""
    from src.tools import build_registry

    try:
        registry = build_registry()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"build_registry() raised unexpectedly: {exc!r}")

    assert registry is not None


def test_build_registry_without_agent_config_returns_well_known_local_tools() -> None:
    """Well-known local tool names must survive a no-config build_registry call."""
    from src.tools import build_registry

    registry = build_registry()
    names = set(registry.tool_names)

    expected = {"load_skill", "backtest", "web_search", "read_file"}
    missing = expected - names
    assert not missing, (
        f"Expected well-known local tools in registry but these are missing: {missing}"
    )


# ---------------------------------------------------------------------------
# MCP server mode regression (vibe-trading-mcp plugin)
# ---------------------------------------------------------------------------


def _import_mcp_server():
    """Import agent/mcp_server.py without executing main().

    Returns:
        The imported mcp_server module.

    Raises:
        ImportError: If the module cannot be imported.
    """
    agent_dir = Path(__file__).resolve().parent.parent
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))

    # Use importlib so we can re-import cleanly in tests.
    if "mcp_server" in sys.modules:
        return sys.modules["mcp_server"]
    return importlib.import_module("mcp_server")


def test_mcp_server_imports_without_raising() -> None:
    """agent/mcp_server.py must import cleanly (no side-effects on import)."""
    try:
        mod = _import_mcp_server()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"import mcp_server raised: {exc!r}")

    assert mod is not None


def test_mcp_server_exposes_expected_tool_count() -> None:
    """The MCP server FastMCP instance must expose the expected number of tools.

    22 tools are documented. We use >= 20 as the floor to tolerate minor
    additions or future removals without breaking this regression gate.
    Uses the public async list_tools() API so this test is stable across
    fastmcp version upgrades.
    """
    import asyncio

    mod = _import_mcp_server()
    mcp_instance = mod.mcp

    tools = asyncio.run(mcp_instance.list_tools())
    tool_count = len(tools)

    assert tool_count >= 20, (
        f"Expected at least 20 MCP server tools, found {tool_count}. "
        "Check whether any tools were accidentally removed from mcp_server.py."
    )


def test_mcp_server_exposes_well_known_tool_names() -> None:
    """Well-known tool names must be registered on the MCP server instance.

    Uses the public async list_tools() API for stability across fastmcp upgrades.
    """
    import asyncio

    mod = _import_mcp_server()
    mcp_instance = mod.mcp

    tools = asyncio.run(mcp_instance.list_tools())
    registered = {t.name for t in tools}

    expected = {
        "list_skills",
        "load_skill",
        "backtest",
        "web_search",
        "read_url",
        "read_document",
        "write_file",
        "read_file",
        "list_swarm_presets",
        "run_swarm",
    }
    missing = expected - registered
    assert not missing, (
        f"MCP server is missing well-known tools: {missing}. "
        "A tool may have been accidentally renamed or removed."
    )