"""Regression test — load_skill (MCP) must page an oversized skill the same
way the internal LoadSkillTool does.

Pre-fix: the MCP wrapper called SkillsLoader.get_content() directly and
returned the complete, uncapped document, bypassing the skeleton/section/
offset paging agent/src/tools/load_skill_tool.py already implements for the
identical "tushare" skill (a 102,890-character document, 10.3x the shared
TOOL_RESULT_LIMIT). The internal agent path, which calls the same tool
through the registry, already gets the capped, paged envelope. Post-fix, the
MCP wrapper delegates to the registry too, matching it exactly.
"""

from __future__ import annotations

import json

import mcp_server
from src.config.limits import TOOL_RESULT_LIMIT

# fastmcp wraps the tool; reach the raw callable.
_load_skill = getattr(mcp_server.load_skill, "fn", None) or getattr(
    mcp_server.load_skill, "__wrapped__", mcp_server.load_skill
)


def test_mcp_load_skill_stays_within_tool_result_limit():
    """An oversized skill must be capped and pageable through MCP too, not
    returned whole."""
    raw = _load_skill(name="tushare")
    assert len(raw) <= TOOL_RESULT_LIMIT, f"{len(raw)} chars, over the {TOOL_RESULT_LIMIT} cap"
    payload = json.loads(raw)
    assert payload["status"] == "ok"
    assert payload["mode"] == "outline"
    assert "next_offset" in payload
    assert payload["complete"] is False


def test_mcp_load_skill_short_skill_still_whole_and_uncorrupted():
    """A skill under the cap must still return complete, byte-identical
    content — the registry envelope adds paging metadata (mode, offset,
    next_offset, complete) even for a whole document, but must not alter it."""
    from src.product.resources.skills import SkillsLoader

    raw = _load_skill(name="candlestick")
    payload = json.loads(raw)
    assert payload["status"] == "ok"
    assert payload["mode"] == "document"
    assert payload["complete"] is True
    assert payload["content"] == SkillsLoader().get_content("candlestick")


def test_mcp_load_skill_error_shape_preserved():
    """An unknown skill must still surface as a clean error, not an exception."""
    raw = _load_skill(name="does-not-exist")
    payload = json.loads(raw)
    assert payload["status"] == "error"
