"""add_goal_evidence and update_research_goal_status must not require
goal_id/expected_goal_id when the caller means "the current goal".

The registered tools (AddGoalEvidenceTool, UpdateResearchGoalStatusTool)
document goal_id as optional, defaulting to the current goal for the
session, and expected_goal_id as optional, defaulting to goal_id. Their
execute() methods implement that fallback via
GoalStore.get_current_snapshot(). The MCP wrappers bypassed the registered
tools entirely, called the store directly, and declared both parameters
required with no fallback: an MCP client that (like the internal agent)
tries to add evidence or update status for "whatever the current goal is"
without re-supplying its id got a hard validation error instead.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def mcp_server():
    """Import agent/mcp_server.py without executing main()."""
    agent_dir = Path(__file__).resolve().parent.parent
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    return importlib.import_module("mcp_server")


@pytest.fixture()
def fresh_goal_store(mcp_server, tmp_path, monkeypatch):
    """Isolate each test's goal store and process-wide session id."""
    from src.goal import GoalStore

    monkeypatch.setattr(mcp_server, "_goal_store", GoalStore(db_path=tmp_path / "g.db"))
    monkeypatch.setattr(mcp_server, "_mcp_session_id", None)
    return mcp_server


def test_add_goal_evidence_falls_back_to_the_current_goal(fresh_goal_store) -> None:
    mcp = fresh_goal_store
    start = json.loads(mcp.start_research_goal(objective="Analyse SPY drawdowns"))
    assert start["status"] == "ok", start
    goal_id = start["snapshot"]["goal"]["goal_id"]

    result = json.loads(mcp.add_goal_evidence(text="Max drawdown was 18% in the sample window."))

    assert result["status"] == "ok", result
    assert result["evidence"]["goal_id"] == goal_id
    assert result["snapshot"]["goal"]["goal_id"] == goal_id


def test_add_goal_evidence_defaults_source_provider_and_type(fresh_goal_store) -> None:
    mcp = fresh_goal_store
    mcp.start_research_goal(objective="Analyse SPY drawdowns")

    result = json.loads(mcp.add_goal_evidence(text="Evidence with no explicit source."))

    assert result["evidence"]["source_provider"] == "agent_tool"
    assert result["evidence"]["source_type"] == "tool_note"


def test_add_goal_evidence_without_a_current_goal_reports_not_found(fresh_goal_store) -> None:
    mcp = fresh_goal_store

    result = json.loads(mcp.add_goal_evidence(text="Nothing to attach this to."))

    assert result["status"] == "error", result
    assert result.get("error_type") == "not_found"


def test_update_research_goal_status_falls_back_to_the_current_goal(fresh_goal_store) -> None:
    mcp = fresh_goal_store
    start = json.loads(mcp.start_research_goal(objective="Analyse SPY drawdowns"))
    goal_id = start["snapshot"]["goal"]["goal_id"]

    result = json.loads(mcp.update_research_goal_status(status="paused"))

    assert result["status"] == "ok", result
    assert result["goal"]["goal_id"] == goal_id
    assert result["goal"]["status"] == "paused"


def test_update_research_goal_status_without_a_current_goal_reports_not_found(fresh_goal_store) -> None:
    mcp = fresh_goal_store

    result = json.loads(mcp.update_research_goal_status(status="paused"))

    assert result["status"] == "error", result
    assert result.get("error_type") == "not_found"


def test_explicit_goal_id_still_works(fresh_goal_store) -> None:
    """An explicit goal_id must keep working exactly as before."""
    mcp = fresh_goal_store
    start = json.loads(mcp.start_research_goal(objective="Analyse SPY drawdowns"))
    goal_id = start["snapshot"]["goal"]["goal_id"]

    result = json.loads(mcp.update_research_goal_status(status="paused", goal_id=goal_id, expected_goal_id=goal_id))

    assert result["status"] == "ok", result
    assert result["goal"]["goal_id"] == goal_id
