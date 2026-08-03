"""MCP tool domain modules.

Each submodule exposes a ``register(mcp: FastMCP) -> None`` function that wires
its read-only / research tools onto the shared FastMCP instance. ``mcp_server.py``
calls :func:`register_all` after constructing the server so the entry point stays
a thin assembler (mirroring the ``api_server.py`` + ``src/api/*_routes.py`` split).

Extracted from the former 2.2k-line ``mcp_server.py`` monolith:
  - skills.py       — list_skills / load_skill
  - goals.py        — research-goal lifecycle (4 tools)
  - analysis.py     — backtest / factor / options / pattern (5 tools)
  - web_files.py    — read_url / read_document / web_search / write_file / read_file
  - trading.py      — read-only connector reads (8 tools)
  - swarm.py        — orchestration + status/history (9 tools)
  - market_data.py  — get_market_data (+ row-cap helpers)
  - research_data.py— fundamentals / flow / news / discovery / journal / shadow (24 tools)
"""

from __future__ import annotations

from fastmcp import FastMCP

from src.mcp_tools import analysis, goals, market_data, research_data, skills, swarm, trading, web_files


def register_all(mcp: FastMCP) -> None:
    """Register every MCP tool domain module onto the FastMCP instance."""
    skills.register(mcp)
    goals.register(mcp)
    analysis.register(mcp)
    web_files.register(mcp)
    trading.register(mcp)
    swarm.register(mcp)
    market_data.register(mcp)
    research_data.register(mcp)


__all__ = ["register_all"]
