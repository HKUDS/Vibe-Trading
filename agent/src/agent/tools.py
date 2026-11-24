"""BaseTool + ToolRegistry: tool infrastructure."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Collection
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.product.tool_policy import ToolPolicy

if TYPE_CHECKING:
    from src.tools.path_utils import FileRoots

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """Tool base class."""

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}
    repeatable: bool = False
    is_readonly: bool = True
    # Cache identical calls only for pure, side-effect-free tools.
    deterministic: bool = False
    # Mutable tools may replay compacted results when opted in, subject to explicit freshness requests.
    replay_after_compaction: bool = False

    @classmethod
    def check_available(cls) -> bool:
        """Check if this tool's dependencies are met."""
        return True

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        """Execute the tool and return a JSON string."""

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}, "required": []},
            },
        }


class FileBoundTool:
    """Tool whose filesystem checks use the host's file-root configuration."""

    def __init__(self, *, roots: FileRoots) -> None:
        self.roots = roots


def host_tool_name(tool: BaseTool, registered: Collection[str]) -> str:
    """Validate a trusted host registration before adding it to either catalog."""
    if not isinstance(tool, BaseTool):
        raise TypeError("host tools must be BaseTool instances")
    name = str(getattr(tool, "name", "")).strip()
    if not name:
        raise ValueError("host tools require a non-empty name")
    if name in registered:
        raise ValueError(f"host tool name collides with registered tool: {name}")
    if bool(getattr(tool, "is_trading_tool", False)):
        raise ValueError("host tools cannot be marked as trading tools")
    if not bool(getattr(tool, "is_readonly", False)):
        raise ValueError("host tools must be read-only")
    if name.startswith(("trading_", "broker_", "mcp_live_")):
        raise ValueError("host tools cannot use a reserved trading tool name")
    if any(token in name.casefold() for token in ("place_order", "cancel_order")):
        raise ValueError("host tools cannot use an order-entry name")
    return name


class ToolRegistry:
    """Tool registry."""

    def __init__(
        self, *, policy: ToolPolicy,
    ) -> None:
        if not isinstance(policy, ToolPolicy):
            raise TypeError("ToolRegistry requires an explicit ToolPolicy")
        self.policy = policy
        self._tools: Dict[str, BaseTool] = {}
        self._import_failures: Dict[str, str] = {}
        self._registration_failures: Dict[str, str] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def register_host_tool(self, tool: BaseTool) -> None:
        """Register one explicitly supplied, non-trading host tool."""
        name = host_tool_name(tool, self._tools)
        self._tools[name] = tool

    def check_policy(self, name: str, params: Dict[str, Any]) -> tuple[bool, str, Dict[str, Any]]:
        """Apply the mandatory registry policy before a hook or a tool can run."""
        return self.policy(name, params)

    def get(self, name: str) -> Optional[BaseTool]:
        """Retrieve a tool by name."""
        return self._tools.get(name)

    def get_definitions(self) -> List[Dict[str, Any]]:
        """Return all tools in OpenAI function calling format."""
        return [t.to_openai_schema() for t in self._tools.values()]

    def record_import_failure(self, module_name: str, reason: str) -> None:
        """Record a tool module that could not be imported during discovery."""
        self._import_failures[module_name] = reason

    def record_registration_failure(self, tool_name: str, reason: str) -> None:
        """Record a discovered tool that could not be instantiated."""
        self._registration_failures[tool_name] = reason

    def _unavailable_reason(self, name: str) -> tuple[str, str] | None:
        registration_reason = self._registration_failures.get(name)
        if registration_reason is not None:
            return name, registration_reason

        for module_name, reason in self._import_failures.items():
            expected_tool_name = module_name.removesuffix("_tool")
            if name in {module_name, expected_tool_name}:
                return module_name, reason
        return None

    def execute(self, name: str, params: Dict[str, Any]) -> str:
        """Execute a tool and guarantee a valid JSON return value."""
        tool = self._tools.get(name)
        if not tool:
            unavailable = self._unavailable_reason(name)
            if unavailable is not None:
                source, reason = unavailable
                return json.dumps(
                    {
                        "status": "error",
                        "error": (
                            f"Tool '{name}' is unavailable because '{source}' failed "
                            f"during registry construction: {reason}"
                        ),
                        "registry_incomplete": True,
                        "failed_source": source,
                    },
                    ensure_ascii=False,
                )

            payload: Dict[str, Any] = {
                "status": "error",
                "error": f"Tool '{name}' not found",
            }
            failure_count = len(self._import_failures) + len(
                self._registration_failures
            )
            if failure_count:
                payload["registry_incomplete"] = True
                payload["registry_failure_count"] = failure_count
                payload["error"] += (
                    f"; the registry is incomplete because {failure_count} tool "
                    "source(s) failed during startup"
                )
            return json.dumps(payload, ensure_ascii=False)
        try:
            # Enforce policy at the shared registry so direct or unoffered calls cannot bypass it.
            allowed, reason, params = self.check_policy(name, params)
            if not allowed:
                return json.dumps({"status": "error", "skipped": True, "error": reason})
            return tool.execute(**params)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return json.dumps({
                "status": "error", "tool": name,
                "error": str(exc),
            }, ensure_ascii=False)

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())

    @property
    def import_failures(self) -> Dict[str, str]:
        """Return a copy of module import failures captured during discovery."""
        return dict(self._import_failures)

    @property
    def registration_failures(self) -> Dict[str, str]:
        """Return a copy of tool instantiation failures captured during build."""
        return dict(self._registration_failures)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
