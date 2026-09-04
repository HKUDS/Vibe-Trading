"""The MCP goal tools must not ask the model to invent a session id.

Issue #885, second half: the in-process tool registry injects the host session
and keeps ``session_id`` optional, while the MCP entry points declared it
required. The two paths declared opposite contracts, and on the MCP path the
model was asked for an internal identifier it has no way to know.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

GOAL_TOOLS = (
    "start_research_goal",
    "get_research_goal",
    "add_goal_evidence",
    "update_research_goal_status",
)


@pytest.fixture(scope="module")
def mcp_server():
    """Import agent/mcp_server.py without executing main()."""
    agent_dir = Path(__file__).resolve().parent.parent
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    return importlib.import_module("mcp_server")


@pytest.fixture()
def tool_parameters(mcp_server) -> dict:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    return {t.name: t.parameters for t in tools}


@pytest.mark.parametrize("name", GOAL_TOOLS)
def test_session_id_is_not_a_required_argument(name, tool_parameters) -> None:
    params = tool_parameters[name]
    assert "session_id" in params["properties"], f"{name} dropped session_id entirely"
    assert "session_id" not in params.get("required", [])


def test_the_other_arguments_stay_required(tool_parameters) -> None:
    """Making session_id optional must not loosen the real inputs.

    goal_id/expected_goal_id are deliberately not in this set: they default
    to the current goal for the session, the same fallback the registered
    AddGoalEvidenceTool/UpdateResearchGoalStatusTool already implement.
    """
    assert tool_parameters["start_research_goal"]["required"] == ["objective"]
    assert tool_parameters["update_research_goal_status"]["required"] == ["status"]
    assert tool_parameters["add_goal_evidence"]["required"] == ["text"]


def test_resolve_session_id_is_stable_within_a_process(mcp_server, monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_mcp_session_id", None)

    first = mcp_server._resolve_session_id()
    second = mcp_server._resolve_session_id("")

    assert first and first == second
    assert first.startswith("mcp-")


def test_resolve_session_id_honours_an_explicit_client_id(mcp_server) -> None:
    assert mcp_server._resolve_session_id("  conv-42  ") == "conv-42"


def test_start_research_goal_works_without_a_session_id(
    mcp_server, tmp_path, monkeypatch
) -> None:
    """The end-to-end point: an omitted id must not become a validation error."""
    from src.goal import GoalStore

    monkeypatch.setattr(mcp_server, "_goal_store", GoalStore(db_path=tmp_path / "g.db"))
    monkeypatch.setattr(mcp_server, "_mcp_session_id", None)

    result = mcp_server.start_research_goal(objective="Analyse SPY drawdowns")

    assert '"status": "ok"' in result
    assert "session_id is required" not in result
