"""Regression: two concurrent MCP connections must not share a goal session.

Pre-fix: _resolve_session_id() fell back to a single process-wide id
(_mcp_session_id) whenever a caller omitted session_id, which is correct
for stdio (one process per client) but wrong for the http/sse transports
this file documents, where one process serves many concurrent
connections. Every such caller collapsed onto the same goal session, so
one client's start_research_goal() silently superseded another's.

Post-fix: _resolve_session_id() prefers FastMCP's own per-connection
ctx.session_id (real mcp-session-id header for StreamableHTTP, a cached
id for the other transports) before falling back to the process-wide id,
so concurrent connections that both omit session_id still get isolated
goal sessions.
"""

from __future__ import annotations

import asyncio
import json

from fastmcp import Client

import mcp_server as ms


def test_two_concurrent_clients_do_not_share_a_goal_session(tmp_path, monkeypatch):
    from src.goal import GoalStore

    monkeypatch.setattr(ms, "_goal_store", GoalStore(db_path=tmp_path / "g.db"))
    monkeypatch.setattr(ms, "_mcp_session_id", None)

    async def scenario():
        async with Client(ms.mcp) as client_a, Client(ms.mcp) as client_b:
            await client_a.call_tool("start_research_goal", {"objective": "USER A thesis: NVDA momentum"})
            await client_b.call_tool("start_research_goal", {"objective": "USER B thesis: bond duration hedge"})
            ra = await client_a.call_tool("get_research_goal", {})
            rb = await client_b.call_tool("get_research_goal", {})
            return json.loads(ra.content[0].text), json.loads(rb.content[0].text)

    snap_a, snap_b = asyncio.run(scenario())
    objective_a = snap_a["snapshot"]["goal"]["objective"]
    objective_b = snap_b["snapshot"]["goal"]["objective"]

    assert objective_a == "USER A thesis: NVDA momentum", (
        f"client A's own get_research_goal() returned {objective_a!r} instead of "
        "its own objective — the two connections shared one goal session"
    )
    assert objective_b == "USER B thesis: bond duration hedge"
    assert snap_a["snapshot"]["goal"]["session_id"] != snap_b["snapshot"]["goal"]["session_id"]



def test_edit_goal_over_mcp_keeps_evidence_and_rejects_other_sessions(tmp_path, monkeypatch):
    from src.goal import GoalStore
    monkeypatch.setattr(ms, "_goal_store", GoalStore(db_path=tmp_path / "edit.db"))
    async def scenario():
        async with Client(ms.mcp) as a, Client(ms.mcp) as b:
            first = await a.call_tool("start_research_goal", {"objective": "Research NVDA", "criteria": ["Check thesis"]})
            first = json.loads(first.content[0].text)["snapshot"]
            goal_id = first["goal"]["goal_id"]
            await a.call_tool("add_goal_evidence", {"text": "Initial evidence"})
            edited = await a.call_tool("update_research_goal", {"objective": "Research NVDA and AMD", "goal_id": goal_id})
            edited = json.loads(edited.content[0].text)
            refused = await b.call_tool("update_research_goal", {"objective": "Cross-session edit", "goal_id": goal_id})
            refused = json.loads(refused.content[0].text)
            assert edited["status"] == "ok"
            assert edited["snapshot"]["goal"]["goal_id"] == goal_id
            assert edited["snapshot"]["evidence_count"] == 1
            assert edited["snapshot"]["criteria"] == first["criteria"]
            assert refused["status"] == "error"
    asyncio.run(scenario())
