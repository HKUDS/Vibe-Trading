"""Fake tools and policy helpers for the v1.2.1 surface matrix tests."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool, ToolRegistry
from src.governance.decisions import PolicyDecision
from src.governance.runtime import RuntimeContext


class CountingTool(BaseTool):
    """Tool that records whether the inner execution path was reached."""

    name = ""
    description = "Fake counted tool."
    parameters = {"type": "object", "properties": {}, "required": []}
    risk_level = "R1_READ"

    def __init__(self, *, name: str, risk_level: str, is_readonly: bool = True) -> None:
        self.name = name
        self.risk_level = risk_level
        self.is_readonly = is_readonly
        self.execution_counter = 0

    def execute(self, **kwargs: Any) -> str:
        self.execution_counter += 1
        return json.dumps({"status": "ok", "tool": self.name, "params": kwargs}, ensure_ascii=False)


class StaticDenyPolicy:
    """Policy that denies every evaluated tool with the manifest risk level."""

    version = "surface-matrix-test-policy"

    def evaluate(
        self,
        *,
        name: str,
        params: dict[str, Any],
        manifest: Any,
        context: RuntimeContext,
    ) -> PolicyDecision:
        del params, context
        return PolicyDecision(
            tool_name=name,
            action="deny",
            risk_level=manifest.risk_level,
            reasons=[f"{manifest.risk_level} denied by surface matrix policy"],
            reason_codes=[f"{manifest.risk_level}_DENIED"],
            policy_engine_version=self.version,
        )


def registry_with(tool: CountingTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool)
    return registry
