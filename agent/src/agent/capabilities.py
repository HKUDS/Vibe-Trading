"""Stable, authenticated capability inventory for the chat composer."""

from __future__ import annotations

from typing import Any

from src.agent.skills import SkillsLoader
from src.agent.tools import ToolRegistry


def tool_category(name: str) -> str:
    """Map legacy tools into stable UI categories without renaming tools."""
    lowered = name.lower()
    if any(token in lowered for token in ("market", "stock", "quote", "price", "symbol", "news")):
        return "market-data"
    if any(token in lowered for token in ("backtest", "factor", "technical", "pattern", "valuation", "financial", "analysis", "screen")):
        return "analysis"
    if any(token in lowered for token in ("trade", "order", "position", "portfolio", "broker", "connector")):
        return "trading"
    if any(token in lowered for token in ("skill", "file", "memory", "shell", "bash", "background")):
        return "system"
    return "other"


def list_capabilities(registry: ToolRegistry | None = None) -> dict[str, list[dict[str, Any]]]:
    """Build the frontend-facing inventory from the same runtime sources."""
    loader = SkillsLoader()
    skills = [
        {"name": skill.name, "category": skill.category or "other", "description": skill.description}
        for skill in loader.skills
    ]
    tools = []
    if registry is not None:
        for name in registry.tool_names:
            tool = registry.get(name)
            if tool is None:
                continue
            declared_category = getattr(tool, "category", "") or ""
            tools.append(
                {
                    "name": tool.name,
                    "category": declared_category if declared_category != "other" else tool_category(tool.name),
                    "read_only": bool(getattr(tool, "is_readonly", True)),
                    "description": tool.description,
                }
            )
    return {"skills": skills, "tools": tools}
