"""Shared helpers and lazy singletons for the MCP tool domain modules.

Extracted from ``mcp_server.py`` so tool implementations can live in focused
domain modules (skills / goals / analysis / trading / swarm / data) without
creating import cycles. ``mcp_server.py`` remains the thin assembler that
creates the FastMCP instance, registers every domain module, and owns the
transport/security wiring.
"""

from __future__ import annotations

import json
from typing import Any

# Lazy-loaded singletons (shared across domain modules).
_skills_loader = None
_registry = None
_goal_store = None

# Fail-closed default: bash / background_run / cancel_background form a remote
# process-control surface once the MCP server is reachable by any client (stdio,
# SSE, or Streamable HTTP), so they stay OFF unless an operator explicitly opts
# in. ``main()`` in mcp_server.py flips this on via --enable-shell-tools or the
# VIBE_TRADING_ENABLE_SHELL_TOOLS env var. Keeping the module-level default off
# means an ASGI/import deployment that never calls ``main()`` also stays safe.
_include_shell_tools = False

_mcp_session_id: str | None = None


def include_shell_tools() -> bool:
    """Return whether shell tools were enabled for the tool registry."""
    return _include_shell_tools


def set_include_shell_tools(value: bool) -> None:
    """Enable/disable shell-tool registration for the shared registry."""
    global _include_shell_tools
    _include_shell_tools = bool(value)


def reset_registry() -> None:
    """Drop the cached tool registry (used when shell tools are re-resolved)."""
    global _registry
    _registry = None


def get_registry():
    """Return the lazily-built in-process tool registry."""
    global _registry
    if _registry is None:
        from src.tools import build_registry

        _registry = build_registry(include_shell_tools=_include_shell_tools)
    return _registry


def get_skills_loader():
    """Return the lazily-built skills loader."""
    global _skills_loader
    if _skills_loader is None:
        from src.agent.skills import SkillsLoader

        _skills_loader = SkillsLoader()
    return _skills_loader


def get_goal_store():
    """Return the shared finance goal store."""
    global _goal_store
    if _goal_store is None:
        from src.goal import GoalStore

        _goal_store = GoalStore()
    return _goal_store


def resolve_session_id(session_id: str = "") -> str:
    """Resolve the goal session, defaulting to this server process's session.

    The in-process tool registry injects the host session and keeps
    ``session_id`` out of its required schema. MCP has no such injection point,
    so these tools used to mark the id required — asking the model to invent an
    internal identifier it has no way to know, the opposite contract from the
    local path (#885). Default instead to one stable id per server process,
    which is the closest MCP equivalent of a host-owned session, while still
    honouring an explicit id from a client that tracks its own conversations.
    """
    global _mcp_session_id
    if cleaned := session_id.strip():
        return cleaned
    if _mcp_session_id is None:
        import uuid

        _mcp_session_id = f"mcp-{uuid.uuid4().hex[:12]}"
    return _mcp_session_id


def json_ok(**payload: Any) -> str:
    """Return a standard MCP JSON success envelope."""
    return json.dumps({"status": "ok", **payload}, ensure_ascii=False, indent=2)


def json_error(error: str, *, error_type: str = "error") -> str:
    """Return a standard MCP JSON error envelope."""
    return json.dumps(
        {"status": "error", "error_type": error_type, "error": error},
        ensure_ascii=False,
        indent=2,
    )


def default_goal_criteria() -> list[str]:
    """Return the MVP finance protocol checklist."""
    from src.goal.context import default_goal_criteria

    return default_goal_criteria()


def clean_list(value: list[str] | None) -> list[str]:
    """Strip empty list values from MCP payloads."""
    return [item.strip() for item in (value or []) if item and item.strip()]


def blank_to_none(value: str | None) -> str | None:
    """Normalize blank MCP strings to None."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def audit_rows_from_payload(value: list[dict[str, Any]] | None):
    """Parse MCP completion audit rows."""
    from src.goal import AuditRow

    rows = []
    for item in value or []:
        criterion_id = str(item.get("criterion_id") or "").strip()
        result = str(item.get("result") or "").strip()
        if not criterion_id or not result:
            raise ValueError("audit rows require criterion_id and result")
        rows.append(
            AuditRow(
                criterion_id=criterion_id,
                result=result,
                evidence_ids=clean_list(item.get("evidence_ids") or []),
                notes=str(item.get("notes") or ""),
            )
        )
    return rows


def risk_tier_from_text(value: str):
    """Parse and validate goal risk tier."""
    from src.goal import RiskTier

    risk_tier = RiskTier(value)
    if risk_tier is RiskTier.LIVE_TRADING_OR_EXECUTION:
        raise ValueError("live trading or execution goals are not supported")
    return risk_tier
