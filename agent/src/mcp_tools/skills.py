"""MCP skill tools (list_skills / load_skill)."""

from __future__ import annotations

import json

from fastmcp import FastMCP

from src.mcp_tools._shared import get_skills_loader


def list_skills() -> str:
    """List all available finance skills with names and descriptions.

    Returns a JSON array of {name, description} for all loaded skills.
    Use load_skill(name) to get the full documentation for any skill.
    """
    loader = get_skills_loader()
    skills = [{"name": s.name, "description": s.description} for s in loader.skills]
    return json.dumps(skills, ensure_ascii=False, indent=2)


def load_skill(name: str) -> str:
    """Load full documentation for a named finance skill.

    Each skill is a comprehensive knowledge document covering methodology,
    code templates, parameters, and examples. Use list_skills() first to
    discover available skills.

    Args:
        name: Skill name (e.g. 'strategy-generate', 'risk-analysis', 'technical-basic').
    """
    loader = get_skills_loader()
    content = loader.get_content(name)
    if content.startswith("Error:"):
        return json.dumps({"status": "error", "error": content}, ensure_ascii=False)
    return json.dumps({"status": "ok", "skill": name, "content": content}, ensure_ascii=False)


def register(mcp: FastMCP) -> None:
    """Register the skill tools with the FastMCP instance."""
    mcp.tool()(list_skills)
    mcp.tool()(load_skill)
