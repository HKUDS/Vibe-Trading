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
    # A successful non-readonly call clears the whole readonly replay cache,
    # since it may have changed what a readonly call would now read (a write
    # to a factor file, a config). Default True preserves that for any tool
    # that could plausibly touch workspace/run_dir state. A non-readonly tool
    # with no such relationship (e.g. remember, which only touches
    # ~/.vibe-trading/memory/) opts out so it doesn't force unrelated readonly
    # results to be re-fetched after compaction.
    invalidates_readonly_cache: bool = True

    @classmethod
    def check_available(cls) -> bool:
        """Check if this tool's dependencies are met.

        Override in subclasses to check for API keys or packages.

        Returns:
            True when discovery can register the tool. The base implementation returns True.
        """
        return True

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        """Execute the tool using its declared arguments.

        Args:
            **kwargs: Arguments defined by the concrete tool's parameter schema.

        Returns:
            A JSON string containing the tool result.
        """

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert the tool definition to OpenAI function calling format.

        Returns:
            A function definition with the tool's name, description, and parameter schema.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}, "required": []},
            },
        }


class FileBoundTool:
    """Tool whose filesystem checks use the host's file-root configuration.

    Args:
        roots: File roots authorized by the host.
    """

    def __init__(self, *, roots: FileRoots) -> None:
        self.roots = roots


def host_tool_name(tool: BaseTool, registered: Collection[str]) -> str:
    """Validate a trusted host registration before adding it to either catalog.

    Args:
        tool: Read-only, non-trading tool supplied by the host.
        registered: Existing tool names to check for collisions.

    Returns:
        The validated tool name with surrounding whitespace removed.

    Raises:
        TypeError: The supplied tool is not a BaseTool.
        ValueError: The name is empty, already registered, or reserved for trading,
            or the tool is marked as trading or is not read-only.
    """
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
    """Store tools and enforce policy at dispatch.

    Args:
        policy: Explicit tool policy used to validate execution arguments.

    Raises:
        TypeError: The supplied policy is not a ToolPolicy.
    """

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
        """Register a tool by its declared name, replacing any entry with that name.

        Args:
            tool: Tool instance to store in the registry.
        """
        self._tools[tool.name] = tool

    def register_host_tool(self, tool: BaseTool) -> None:
        """Register one explicitly supplied, non-trading host tool.

        Host tools enter the registry through explicit registration.

        Args:
            tool: Read-only host tool with a unique, non-reserved name.

        Raises:
            TypeError: The supplied tool is not a BaseTool.
            ValueError: The tool is ineligible or its name is empty, reserved, or already registered.
        """
        name = host_tool_name(tool, self._tools)
        self._tools[name] = tool

    def check_policy(self, name: str, params: Dict[str, Any]) -> tuple[bool, str, Dict[str, Any]]:
        """Apply the mandatory registry policy before a hook or a tool can run.

        Args:
            name: Tool name to check against the active policy.
            params: Candidate arguments for the tool call.

        Returns:
            Whether the call is allowed, the decision reason, and the policy-adjusted arguments.
        """
        return self.policy(name, params)

    def get(self, name: str) -> Optional[BaseTool]:
        """Retrieve a tool by name.

        Args:
            name: Registered tool name to look up.

        Returns:
            The corresponding tool, or None when the name is absent.
        """
        return self._tools.get(name)

    def get_definitions(self) -> List[Dict[str, Any]]:
        """List all tools in OpenAI function calling format.

        Returns:
            A function definition for each registered tool in registry order.
        """
        return [t.to_openai_schema() for t in self._tools.values()]

    def record_import_failure(self, module_name: str, reason: str) -> None:
        """Record a tool module that could not be imported during discovery.

        Args:
            module_name: Name of the module that failed to import.
            reason: Diagnostic describing the import failure.
        """
        self._import_failures[module_name] = reason

    def record_registration_failure(self, tool_name: str, reason: str) -> None:
        """Record a discovered tool that could not be instantiated.

        Args:
            tool_name: Name of the tool that could not be registered.
            reason: Diagnostic describing the registration failure.
        """
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
        """Check registry policy and invoke the named tool if allowed.

        Args:
            name: Tool name to look up and authorize.
            params: Arguments to check before invoking the tool.

        Returns:
            The tool's JSON result, or a JSON error for missing tools, policy refusals,
            or execution failures.
        """
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
        """List tool names in registry order.

        Returns:
            A list of the currently registered names.
        """
        return list(self._tools.keys())

    @property
    def import_failures(self) -> Dict[str, str]:
        """Report module import failures captured during discovery.

        Returns:
            A copy of the mapping from failed module names to diagnostic messages.
        """
        return dict(self._import_failures)

    @property
    def registration_failures(self) -> Dict[str, str]:
        """Report tool instantiation failures captured during assembly.

        Returns:
            A copy of the mapping from failed tool names to diagnostic messages.
        """
        return dict(self._registration_failures)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
