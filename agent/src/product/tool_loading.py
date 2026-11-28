"""Expose exact tool schemas on demand while keeping the full catalog visible."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any

from src.agent.tools import BaseTool, ToolRegistry


@lru_cache(maxsize=1)
def loading_policy() -> dict[str, Any]:
    """Read the shipped tool-loading policy.

    Returns:
        The decoded settings from the JSON file beside this module.
    """
    return json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))


class DeferredToolRegistry(ToolRegistry):
    """Expose schemas per conversation while retaining the source tools' execution permissions.

    Args:
        source: Registry from which to copy tools, policy, and discovery diagnostics.
    """

    def __init__(self, source: ToolRegistry) -> None:
        super().__init__(policy=source.policy)
        self.hooks = getattr(source, "hooks", None)
        self.sandbox = getattr(source, "sandbox", None)
        self.background = getattr(source, "background", None)
        self._tools = dict(source._tools)
        self._import_failures = dict(source.import_failures)
        self._registration_failures = dict(source.registration_failures)
        self._lock = RLock()
        self.register(LoadToolsTool(self))
        self.reset_exposure()

    def reset_exposure(self) -> None:
        """Start a new conversation with only the initial schemas exposed."""
        with self._lock:
            self._loaded = dict.fromkeys([
                *(name for name in loading_policy()["initial_tools"] if name in self._tools),
                "load_tools",
            ])

    def exposed_names(self) -> list[str]:
        """Capture the exposed tool names for use in a later turn.

        Returns:
            A list of exposed names in request order.
        """
        with self._lock:
            return list(self._loaded)

    def restore_exposure(self, names: list[str]) -> None:
        """Expose the schemas an earlier turn of the same conversation loaded.

        Order is kept. Unavailable names are skipped and load_tools stays exposed.

        Args:
            names: Names returned by exposed_names for the earlier turn.
        """
        with self._lock:
            restored = dict.fromkeys(name for name in names if name in self._tools)
            restored.setdefault("load_tools")
            self._loaded = restored

    def request_definitions(self) -> list[dict[str, Any]]:
        """Collect schemas for the tools exposed on this question.

        Returns:
            Unmodified tool schemas in exposure order.
        """
        with self._lock:
            return [self._tools[name].to_openai_schema() for name in self._loaded]

    def catalog(self) -> str:
        """List available tools for discovery.

        Returns:
            One line per discoverable tool, with its exact name and bounded description.
        """
        limit = loading_policy()["catalog_description_chars"]
        lines = []
        for name, tool in self._tools.items():
            if name == "load_tools":
                continue
            hint = " ".join((tool.description or "").split())
            if len(hint) > limit:
                hint = hint[:limit].rsplit(" ", 1)[0] + "…"
            lines.append(f"- {name}: {hint}")
        return "\n".join(lines)

    def expose(self, names: list[str]) -> dict[str, Any]:
        """Load known names atomically without adding tools absent from the registry.

        Args:
            names: Nonempty list of exact tool names selected from the catalog.

        Returns:
            An acknowledgement of the loaded schemas, or an error with no exposure change.
        """
        if not isinstance(names, list) or not names or any(not isinstance(n, str) for n in names):
            return {"status": "error", "error": "names must be a non-empty list of exact tool names"}
        unknown = [name for name in names if name not in self._tools]
        if unknown:
            return {"status": "error", "unknown_tools": unknown, "available_tools": self.tool_names}
        with self._lock:
            # Append new schemas so previously exposed definitions retain their
            # prefix/order for providers that cache common prompt prefixes.
            self._loaded.update(dict.fromkeys(names))
        result: dict[str, Any] = {
            "status": "ok",
            "loaded": list(dict.fromkeys(names)),
            "message": "Full schemas are available in the next request. Request them through the host's tool-call protocol in your next reply; loading has not executed them.",
        }
        return result


class LoadToolsTool(BaseTool):
    """Select exact schemas from the current run's complete tool catalog.

    Args:
        registry: Deferred registry whose next request will expose loaded schemas.
    """

    name = "load_tools"
    description = (
        "Load full argument schemas for tools named in the system catalog. "
        "Select all tools needed for the next steps in one call, then request them "
        "through the host's tool-call protocol in the next turn. This only exposes "
        "schemas; it executes no tool."
    )
    parameters = {
        "type": "object",
        "properties": {
            "names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        },
        "required": ["names"],
    }
    repeatable = True

    @classmethod
    def check_available(cls) -> bool:
        """Reserve the tool for explicit installation by the deferred registry.

        Returns:
            False to exclude this tool from global subclass discovery.
        """
        return False

    def __init__(self, registry: DeferredToolRegistry) -> None:
        self.registry = registry

    def execute(self, names: list[str], **kwargs: Any) -> str:
        """Expose schemas without invoking a tool or changing its permissions.

        Args:
            names: Nonempty list of exact names to expose.
            **kwargs: Additional arguments accepted by the tool interface and ignored here.

        Returns:
            JSON acknowledgement or error from schema exposure.
        """
        return json.dumps(self.registry.expose(names), ensure_ascii=False)


def prepare_registry(registry: ToolRegistry) -> ToolRegistry:
    """Select deferred exposure for large registries when enabled in config.

    Args:
        registry: Registry supplying available tools and their execution policy.

    Returns:
        A fresh deferred registry when the input is already deferred or qualifies
        for lazy loading, otherwise the input registry.
    """
    from src.config.accessor import get_env_config

    if isinstance(registry, DeferredToolRegistry):
        return DeferredToolRegistry(registry)
    if (
        isinstance(registry, ToolRegistry)
        and get_env_config().agent_tuning.vibe_trading_tool_loading == "lazy"
        and len(registry) >= loading_policy()["minimum_tools"]
    ):
        return DeferredToolRegistry(registry)
    return registry


def request_definitions(registry: ToolRegistry) -> list[dict[str, Any]]:
    """Collect the tool schemas visible on the current request.

    Args:
        registry: Registry supplying exposed or ordinary tool definitions.

    Returns:
        Exposed schemas for a deferred registry, all definitions for a regular
        registry, or an empty list when definitions are unavailable.
    """
    if isinstance(registry, DeferredToolRegistry):
        return registry.request_definitions()
    definitions = getattr(registry, "get_definitions", None)
    return definitions() if callable(definitions) else []
