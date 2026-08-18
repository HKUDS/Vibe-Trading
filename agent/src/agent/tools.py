"""BaseTool + ToolRegistry: tool infrastructure."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)
from typing import Any, Dict, List, Optional


class BaseTool(ABC):
    """Tool base class.

    Attributes:
        name: Unique tool identifier.
        description: Tool description shown to the LLM.
        parameters: Parameter definition in JSON Schema format.
        repeatable: Whether the tool may be called more than once.
    """

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}
    repeatable: bool = False
    is_readonly: bool = True

    @classmethod
    def check_available(cls) -> bool:
        """Check if this tool's dependencies are met.

        Override in subclasses to check for API keys, packages, etc.
        Tools that return False are excluded from the registry.
        """
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


class ToolRegistry:
    """Tool registry."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}
        self._import_failures: Dict[str, str] = {}
        self._registration_failures: Dict[str, str] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

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
