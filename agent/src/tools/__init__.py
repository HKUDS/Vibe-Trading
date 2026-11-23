"""Tool registry for built-ins and explicitly supplied host tools.

Built-in classes are discovered from ``src/tools`` for compatibility with the
existing catalog. Host tools supplied through ``register_tool`` are added only
to that client's registry and never enter this discovery path. This keeps a
third-party class import from changing every process-wide registry.

Tools with missing dependencies can override check_available() → False
to be silently excluded from the registry.
"""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy

import importlib
import logging
import pkgutil
import uuid
from collections.abc import Mapping
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from src.agent.tools import BaseTool, FileBoundTool, ToolRegistry

if TYPE_CHECKING:
    from src.product.resources.hooks import HookManager
    from src.config.schema import AgentConfig
    from src.memory.persistent import PersistentMemory

logger = logging.getLogger(__name__)

_SUBCLASSES_CACHE: list[type[BaseTool]] | None = None
_DISCOVERY_FAILURES: dict[str, str] = {}
_SHELL_TOOL_NAMES = {"bash", "background_run", "cancel_background"}


def _discover_subclasses() -> list[type[BaseTool]]:
    """Import all modules in this package, then collect BaseTool subclasses.

    Results are cached after the first call.

    Returns:
        List of concrete BaseTool subclasses with a non-empty name.
    """
    global _SUBCLASSES_CACHE, _DISCOVERY_FAILURES
    if _SUBCLASSES_CACHE is not None:
        return _SUBCLASSES_CACHE

    pkg_dir = str(Path(__file__).parent)
    discovery_failures: dict[str, str] = {}
    for _, module_name, _ in pkgutil.iter_modules([pkg_dir]):
        if module_name.startswith("_"):
            continue
        try:
            importlib.import_module(f"src.tools.{module_name}")
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            discovery_failures[module_name] = reason
            # Stays at WARNING: an operator who cannot see *which* module
            # dropped out is back to the silent partial registry of #1124.
            # The aggregate line below counts them; this one names them.
            logger.warning(
                "Skipped src.tools.%s during discovery: %s", module_name, reason
            )

    classes: list[type[BaseTool]] = []
    queue = deque(BaseTool.__subclasses__())
    while queue:
        cls = queue.popleft()
        module_name = str(getattr(cls, "__module__", ""))
        if cls.name and (
            module_name.startswith("src.tools.")
            or module_name == "src.product.tool_loading"
        ):
            classes.append(cls)
        queue.extend(cls.__subclasses__())

    _SUBCLASSES_CACHE = classes
    _DISCOVERY_FAILURES = discovery_failures
    return classes


def session_bound_tool_classes() -> frozenset[type[BaseTool]]:
    """Tool classes ``build_registry`` binds to the host session.

    Each is built with the session id and event callback: they create or
    mutate the session's research goal (or schedule runs for it), and the LLM
    never knows the session id. An instance of one acts on that session
    whoever calls it.

    Returns:
        The goal tools, the research autopilot and scheduled research.
    """
    from src.tools.autopilot_tool import RunResearchAutopilotTool
    from src.tools.goal_tool import (
        AddGoalEvidenceTool,
        GetResearchGoalTool,
        StartResearchGoalTool,
        UpdateResearchGoalStatusTool,
        UpdateResearchGoalTool,
    )
    from src.tools.scheduled_research_tool import ScheduledResearchTool
    from src.tools.plan_tool import PlanTool
    from src.tools.ask_user_tool import AskUserTool

    return frozenset({
        StartResearchGoalTool,
        GetResearchGoalTool,
        AddGoalEvidenceTool,
        UpdateResearchGoalStatusTool,
        UpdateResearchGoalTool,
        RunResearchAutopilotTool,
        ScheduledResearchTool,
        PlanTool,
        AskUserTool,
    })


def build_registry(
    *,
    policy: ToolPolicy,
    persistent_memory: "PersistentMemory | None" = None,
    include_shell_tools: bool = False,
    agent_config: "AgentConfig | None" = None,
    session_id: str | None = None,
    event_callback: Callable[[str, dict], None] | None = None,
    warn_callback: Callable[[str], None] | None = None,
    interactive: bool | None = None,
    cancel_event: Any | None = None,
    background_manager: Any | None = None,
    background_scope: Any | None = None,
    _mcp_server_tool_name_segments: Mapping[str, str] | None = None,
    host_tools: list[BaseTool] | None = None,
    hook_manager: HookManager | None = None,
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
        session_id: Optional current session id injected into local tools that
            persist per-session state. Also used as the background-task owner
            when no explicit ``background_scope`` is given.
        event_callback: Optional event callback injected into local tools that
            mutate session-scoped state.
        warn_callback: Optional callable invoked with operator-facing warning
            messages. When provided, server-name collision warnings are passed
            to this callback in addition to the standard logger so CLI and
            SessionService can surface them to operators.
        interactive: Whether the session is an interactive TTY. Governs whether
            a live-broker channel with no cached OAuth token is registered: a
            non-interactive run (``serve`` / swarm) skips an unauthorized live
            channel rather than blocking on a browser that cannot open
            (SPEC Transport §4). ``None`` (default) auto-detects via
            ``sys.stdin.isatty()``.
        background_manager: Shared background task table. Defaults to the
            process-wide one.
        background_scope: Who owns the background tasks this registry can
            start. When omitted the scope is derived from ``session_id``, or is
            private to this registry when there is no session either. The
            resolved handle is exposed as ``registry.background`` so the host
            can give the same one to ``AgentRuntime`` and keep task results and
            completion notifications inside one conversation.

    Returns:
        ToolRegistry containing all available local tools followed by any
        successfully discovered MCP tools.
    """
    from src.tools.background_tools import (
        BackgroundScope,
        BackgroundRunTool,
        CancelBackgroundTool,
        CheckBackgroundTool,
        get_background_manager,
    )
    from src.tools.remember_tool import RememberTool
    from src.tools.spawn_agent_tool import SpawnAgentTool
    from src.tools.swarm_tool import SwarmTool

    from src.product.resources.hooks import load_hooks

    session_injected_classes = session_bound_tool_classes()
    classes = _discover_subclasses()
    registry = ToolRegistry(policy=policy)
    sandbox = policy.sandbox
    registry.sandbox = sandbox
    registry.hooks = hook_manager or load_hooks()

    bg_scope = background_scope or (
        BackgroundScope(owner_id=f"session:{session_id}")
        if session_id
        else getattr(background_manager, "scope", None)
        or BackgroundScope(owner_id=f"isolated:{uuid.uuid4().hex}")
    )
    bg_base = background_manager or get_background_manager(sandbox=sandbox)
    bg = bg_base.for_scope(bg_scope, sandbox=sandbox)
    # The loop drains the same handle the tools write to, so a task's result
    # reaches the conversation that started it and no other.
    registry.background = bg
    for module_name, reason in _DISCOVERY_FAILURES.items():
        registry.record_import_failure(module_name, reason)

    for cls in classes:
        try:
            if cls.name in _SHELL_TOOL_NAMES and not include_shell_tools:
                logger.info("Tool %s disabled by shell tool policy", cls.name)
                continue
            if not cls.check_available():
                logger.info("Tool %s unavailable, skipping", cls.name)
                continue
            if cls is RememberTool and persistent_memory is not None:
                registry.register(cls(memory=persistent_memory))
            elif cls in (BackgroundRunTool, CheckBackgroundTool, CancelBackgroundTool):
                registry.register(cls(background=bg))
            elif cls in session_injected_classes:
                kwargs = {"roots": policy.file_roots} if issubclass(cls, FileBoundTool) else {}
                registry.register(cls(default_session_id=session_id, event_callback=event_callback, **kwargs))
            elif cls.name == "analyze_image":
                registry.register(cls(policy=policy))
            elif cls is SwarmTool:
                registry.register(
                    cls(
                        policy=policy,
                        include_shell_tools=include_shell_tools,
                        event_callback=event_callback,
                        session_id=session_id,
                        cancel_event=cancel_event,
                    )
                )
            elif cls is SpawnAgentTool:
                # Reads this registry when it runs, so MCP tools appended
                # below are part of the child's tool set too.
                registry.register(
                    cls(
                        registry,
                        cancel_event=cancel_event,
                        session_id=session_id,
                        event_callback=event_callback,
                    )
                )
            elif issubclass(cls, FileBoundTool):
                registry.register(cls(roots=policy.file_roots))
            elif cls.name == "bash":
                registry.register(cls(sandbox=sandbox))
            else:
                registry.register(cls())
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            registry.record_registration_failure(cls.name, reason)
            logger.warning("Failed to register tool %s: %s", cls.name, reason)

    local_failure_count = len(registry.import_failures) + len(
        registry.registration_failures
    )
    if local_failure_count:
        summary = (
            f"Registered {len(registry)} local tools; {local_failure_count} tool "
            "source(s) failed during registry construction"
        )
        logger.warning(summary)

    if agent_config and agent_config.mcp_servers:
        from src.tools.mcp import build_mcp_tool_wrappers, resolve_mcp_server_tool_name_segments

        if _mcp_server_tool_name_segments is None:
            local_server_names = resolve_mcp_server_tool_name_segments(
                agent_config.mcp_servers.keys(),
                warn_callback=warn_callback,
            )
        else:
            local_server_names = {
                server_name: _mcp_server_tool_name_segments[server_name]
                for server_name in agent_config.mcp_servers
            }

        if interactive is None:
            import sys

            interactive = sys.stdin.isatty()

        for server_name, server_config in agent_config.mcp_servers.items():
            try:
                # Live brokers (e.g. Robinhood) gate their order-placing tools
                # behind the mandate + kill switch; reads stay plain (read-only).
                # Detection is by config key OR URL host, so a live-broker URL
                # under an aliased key cannot bypass the gate.
                from src.live.registry import (
                    is_live_broker,
                    should_register_live_channel,
                    wrap_live_broker_tools,
                )

                server_url = server_config.url
                live = is_live_broker(server_name, server_url)

                # Headless / no-token: skip an unauthorized live channel rather
                # than block on a browser that can't open (SPEC Transport §4).
                if live:
                    cache_dir = (
                        server_config.auth.cache_dir
                        if server_config.auth is not None
                        else None
                    )
                    if not should_register_live_channel(
                        interactive=interactive, url=server_url, cache_dir=cache_dir
                    ):
                        profile_hint = (
                            "ibkr-live-official-mcp-readonly"
                            if server_name.strip().lower() == "ibkr"
                            else f"{server_name}-live-mcp"
                        )
                        skip_msg = (
                            f"{server_name} live connector configured but not authorized — "
                            f"run `vibe-trading connector authorize {profile_hint}` "
                            f"on a desktop session"
                        )
                        logger.warning(skip_msg)
                        if warn_callback is not None:
                            warn_callback(skip_msg)
                        continue
                    info_msg = (
                        f"{server_name} live connector is available through trading_* tools; "
                        "broker-specific MCP wrappers are hidden from the agent registry"
                    )
                    logger.info(info_msg)
                    if warn_callback is not None:
                        warn_callback(info_msg)
                    continue

                wrappers = build_mcp_tool_wrappers(
                    server_name,
                    server_config,
                    local_server_name=local_server_names[server_name],
                )
                if live:
                    wrappers = wrap_live_broker_tools(
                        server_name, wrappers, url=server_url
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

    for host_tool in host_tools or []:
        registry.register_host_tool(host_tool)

    return registry


def build_filtered_registry(
    tool_names: list[str],
    *,
    policy: ToolPolicy,
    include_shell_tools: bool = False,
    skill_allowlist: list[str] | None = None,
    background_manager: Any | None = None,
    background_scope: Any | None = None,
) -> ToolRegistry:
    """Build a ToolRegistry with only specified tools.

    Local-tools-only filtered builder. Swarm workers should call
    :func:`build_swarm_registry` instead so they can opt into remote MCP
    tools when the operator has configured them. This function is preserved
    for callers that explicitly want the local-only path.

    Args:
        tool_names: Tool names to include.
        include_shell_tools: Whether to include filtered shell execution tools.
        skill_allowlist: When not ``None``, the ``load_skill`` tool (if
            whitelisted) is rebuilt to refuse skill names outside this list,
            so a documented skill boundary is enforced at runtime.
        background_manager: Shared background task table.
        background_scope: Owner of the background tasks this registry starts.

    Returns:
        ToolRegistry containing only the requested tools.
    """
    full = build_registry(
        policy=policy,
        include_shell_tools=include_shell_tools,
        background_manager=background_manager,
        background_scope=background_scope,
    )
    return _filter_registry(
        full,
        tool_names,
        include_shell_tools=include_shell_tools,
        skill_allowlist=skill_allowlist,
    )


def build_swarm_registry(
    tool_names: list[str],
    *,
    policy: ToolPolicy,
    agent_config: "AgentConfig | None" = None,
    include_shell_tools: bool = False,
    skill_allowlist: list[str] | None = None,
    background_manager: Any | None = None,
    background_scope: Any | None = None,
) -> ToolRegistry:
    """Build a per-worker registry that merges local + remote MCP tools.

    Swarm workers receive a strict whitelist (``agent_spec.tools``). This
    builder honors that whitelist while letting operator-configured MCP
    servers contribute additional tools by name (``mcp_<server>_<tool>``).
    Tools the whitelist requests but the operator has NOT surfaced — either
    because ``agent_config`` is ``None``, the named MCP server is absent, or
    the server's ``enabled_tools`` allowlist excluded it — are dropped with
    an operator-facing warning instead of failing the worker.

    Trust model: ``agent_config`` is resolved at server boot from a static
    file or env var; callers of swarm entry points (e.g. an external MCP
    client driving ``mcp_server.py::run_swarm``) cannot inject MCP server
    URLs through this path.

    Args:
        tool_names: Per-agent tool whitelist from the preset.
        agent_config: Optional resolved agent config. When provided, remote
            MCP wrappers are appended to the candidate pool before filtering.
            Pass ``None`` to keep the worker strictly local.
        include_shell_tools: Whether shell-execution tools are eligible.
        skill_allowlist: When not ``None``, the ``load_skill`` tool (if
            whitelisted) is rebuilt to refuse skill names outside this list,
            enforcing the per-worker ``skills:`` boundary at runtime.
        background_manager: Shared background task table.
        background_scope: Owner of the background tasks this worker starts.
            Swarm workers should pass one scoped to their run and identity so
            concurrent workers never see each other's tasks. Omitting it gives
            the worker a private scope rather than a shared one.

    Returns:
        ToolRegistry containing the whitelist intersection of local tools
        and any operator-surfaced MCP tools.
    """
    swarm_agent_config, swarm_local_server_names = _prune_agent_config_for_swarm_tools(
        agent_config,
        tool_names,
    )
    full = build_registry(
        policy=policy,
        agent_config=swarm_agent_config,
        include_shell_tools=include_shell_tools,
        background_manager=background_manager,
        background_scope=background_scope,
        _mcp_server_tool_name_segments=swarm_local_server_names,
    )
    return _filter_registry(
        full,
        tool_names,
        include_shell_tools=include_shell_tools,
        skill_allowlist=skill_allowlist,
    )


def _prune_agent_config_for_swarm_tools(
    agent_config: "AgentConfig | None",
    tool_names: list[str],
) -> tuple["AgentConfig | None", dict[str, str] | None]:
    """Keep only MCP servers whose local tool prefix appears in ``tool_names``."""
    if not agent_config or not agent_config.mcp_servers:
        return agent_config, None

    requested_mcp_tool_names = [name for name in tool_names if name.startswith("mcp_")]
    if not requested_mcp_tool_names:
        return None, None

    from src.config.schema import AgentConfig
    from src.tools.mcp import resolve_mcp_server_tool_name_segments

    local_server_names = resolve_mcp_server_tool_name_segments(agent_config.mcp_servers.keys())
    selected_servers = {
        server_name: server_config
        for server_name, server_config in agent_config.mcp_servers.items()
        if any(
            tool_name.startswith(f"mcp_{local_server_names[server_name]}_")
            for tool_name in requested_mcp_tool_names
        )
    }
    selected_local_server_names = {
        server_name: local_server_names[server_name]
        for server_name in selected_servers
    }
    return AgentConfig(mcp_servers=selected_servers), selected_local_server_names


def _filter_registry(
    full: ToolRegistry,
    tool_names: list[str],
    *,
    include_shell_tools: bool,
    skill_allowlist: list[str] | None = None,
) -> ToolRegistry:
    """Project a full registry down to a whitelist with consistent drop logging."""
    filtered = ToolRegistry(policy=full.policy)
    filtered.background = getattr(full, "background", None)
    filtered.hooks = getattr(full, "hooks", None)
    for name in tool_names:
        tool = full.get(name)
        if tool:
            filtered.register(tool)
        else:
            logger.warning(
                "Requested tool %r is unavailable and was dropped from the "
                "filtered registry (include_shell_tools=%s); a preset that "
                "depends on it cannot execute it.",
                name, include_shell_tools,
            )
    if skill_allowlist is not None and filtered.get("load_skill") is not None:
        # Rebuild load_skill with the boundary baked in. ``register`` replaces
        # by name, so the unrestricted auto-discovered instance is dropped.
        from src.tools.load_skill_tool import LoadSkillTool

        filtered.register(LoadSkillTool(allowed_skills=frozenset(skill_allowlist)))
    return filtered


__all__ = ["build_registry", "build_filtered_registry", "build_swarm_registry"]
