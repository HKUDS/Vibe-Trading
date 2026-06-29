"""Goal-state payload helpers for WebSocket channel adapters."""

from __future__ import annotations

from typing import Any


def goal_state_ws_blob(meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a WebSocket payload for the current active goal state.

    The WebSocket gateway stores goal snapshots in session metadata when they
    are available. This helper normalizes either a direct ``goal_state`` payload
    or compact goal metadata into the client event shape. It returns an inactive
    payload when no goal metadata is present.
    """
    if not isinstance(meta, dict):
        return {"active": False, "active_goals": [], "completed_goals": []}
    goal_state = meta.get("goal_state")
    if isinstance(goal_state, dict):
        return {
            "active": bool(goal_state.get("active")),
            "active_goals": list(goal_state.get("active_goals") or []),
            "completed_goals": list(goal_state.get("completed_goals") or []),
        }
    goal = meta.get("active_goal") or meta.get("goal")
    if isinstance(goal, dict):
        return {"active": True, "active_goals": [goal], "completed_goals": []}
    return {"active": False, "active_goals": [], "completed_goals": []}
