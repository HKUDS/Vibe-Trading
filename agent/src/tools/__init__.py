"""Tool registry: auto-discovery via BaseTool.__subclasses__().

Adding a new tool:
  1. Create a file in src/tools/ with a class extending BaseTool
  2. Done. It's automatically discovered and registered.

Tools with missing dependencies can override check_available() → False
to be silently excluded from the registry.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from src.agent.tools import BaseTool, ToolRegistry

if TYPE_CHECKING:
    from src.config.schema import AgentConfig
    from src.memory.persistent import PersistentMemory

logger = logging.getLogger(__name__)

_SUBCLASSES_CACHE: list[type[BaseTool]] | None = None
_SHELL_TOOL_NAMES = {"bash", "background_run"}


def _discover_subclasses() -> list[type[BaseTool]]:
    """Import all modules in this package, then collect BaseTool subclasses.

    Results are cached after the first call.

    Returns:
        List of concrete BaseTool subclasses with a non-empty name.
    """
    global _SUBCLASSES_CACHE
    if _SUBCLASSES_CACHE is not None:
        return _SUBCLASSES_CACHE

    pkg_dir = str(Path(__file__).parent)
    for _, module_name, _ in pkgutil.iter_modules([pkg_dir]):
        if module_name.startswith("_"):
            continue
        try:
            importlib.import_module(f"src.tools.{module_name}")
        except Exception as exc:
            logger.warning("Skipped src.tools.%s: %s", module_name, exc)

    classes: list[type[BaseTool]] = []
    queue = deque(BaseTool.__subclasses__())
    while queue:
        cls = queue.popleft()
        if cls.name:
            classes.append(cls)
        queue.extend(cls.__subclasses__())

    _SUBCLASSES_CACHE = classes
    return classes


def build_registry(
    *,
    persistent_memory: "PersistentMemory | None" = None,
    include_shell_tools: bool = False,
    agent_config: "AgentConfig | None" = None,
    warn_callback: Callable[[str], None] | None = None,
) -> ToolRegistry:
    """Build the tool registry via auto-discovery, optionally enriched with MCP tools.

    Local tools are discovered and registered first. When ``agent_config``
    provides one or more MCP server definitions, remote tools are appended
    after the local tools. Each MCP server is isolated: a failure to connect
    or discover tools for one server emits a warning and skips that server
    without affecting local tools or other MCP servers.

    Args:
        persistent_memory: Shared PersistentMemory instance. Injected into
            tools that need it (e.g. RememberTool) so all tools share one
            instance instead of each creating their own.
        include_shell_tools: Whether to include tools that execute shell
            commands. Local CLI/stdin entry points can enable this; networked
            server entry points should keep it disabled unless explicitly
            opted in.
        agent_config: Optional structured agent config. When provided and
            non-empty, MCP tools are appended to the registry after local
            tool discovery. Pass ``None`` (default) to preserve existing
            behavior with no MCP integration.
        warn_callback: Optional callable invoked with operator-facing warning
            messages. When provided, server-name collision warnings are passed
            to this callback in addition to the standard logger so CLI and
            SessionService can surface them to operators.

    Returns:
        ToolRegistry containing all available local tools followed by any
        successfully discovered MCP tools.
    """
    from src.tools.remember_tool import RememberTool
    from src.tools.swarm_tool import SwarmTool

    registry = ToolRegistry()
    for cls in _discover_subclasses():
        try:
            if cls.name in _SHELL_TOOL_NAMES and not include_shell_tools:
                logger.info("Tool %s disabled by shell tool policy", cls.name)
                continue
            if not cls.check_available():
                logger.info("Tool %s unavailable, skipping", cls.name)
                continue
            if cls is RememberTool and persistent_memory is not None:
                registry.register(cls(memory=persistent_memory))
            elif cls is SwarmTool:
                registry.register(cls(include_shell_tools=include_shell_tools))
            else:
                registry.register(cls())
        except Exception as exc:
            logger.warning("Failed to register tool %s: %s", cls.name, exc)

    if agent_config and agent_config.mcp_servers:
        from src.tools.mcp import build_mcp_tool_wrappers, resolve_mcp_server_tool_name_segments

        local_server_names = resolve_mcp_server_tool_name_segments(
            agent_config.mcp_servers.keys(),
            warn_callback=warn_callback,
        )

        for server_name, server_config in agent_config.mcp_servers.items():
            try:
                wrappers = build_mcp_tool_wrappers(
                    server_name,
                    server_config,
                    local_server_name=local_server_names[server_name],
                )
                for tool in wrappers:
                    registry.register(tool)
                logger.info(
                    "Registered %d MCP tool(s) from server '%s'",
                    len(wrappers),
                    server_name,
                )
            except Exception as exc:
                skip_msg = f"MCP server '{server_name}' skipped: {exc}"
                logger.warning("Skipped MCP server '%s': %s", server_name, exc)
                if warn_callback is not None:
                    warn_callback(skip_msg)

    return registry


def build_filtered_registry(tool_names: list[str], *, include_shell_tools: bool = False) -> ToolRegistry:
    """Build a ToolRegistry with only specified tools.

    TODO(v1): Keep this path local-only for now. Swarm workers currently use
    filtered registries, and v1 MCP support does not propagate agent_config
    into swarm execution until a separate design pass defines how remote MCP
    tools should be configured and constrained there.

    Args:
        tool_names: Tool names to include.
        include_shell_tools: Whether to include filtered shell execution tools.

    Returns:
        ToolRegistry containing only the requested tools.
    """
    full = build_registry(include_shell_tools=include_shell_tools)
    filtered = ToolRegistry()
    for name in tool_names:
        tool = full.get(name)
        if tool:
            filtered.register(tool)
    return filtered


__all__ = ["build_registry", "build_filtered_registry"]
