"""Fixture inputs for the remote shell and live-write deny-barrier demo."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool, ToolRegistry

RUN_ID = "demo_remote_shell_live_write_trap"


class CountingTool(BaseTool):
    """Tool that proves whether the inner execution path was reached."""

    description = "Deterministic counted tool."
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, *, name: str, risk_level: str, is_readonly: bool) -> None:
        self.name = name
        self.risk_level = risk_level
        self.is_readonly = is_readonly
        self.execution_counter = 0

    def execute(self, **kwargs: Any) -> str:
        self.execution_counter += 1
        return json.dumps({"status": "executed", "tool": self.name, "params": kwargs}, ensure_ascii=False)


def registry_with(tool: CountingTool) -> ToolRegistry:
    """Return a registry containing one deterministic tool."""
    registry = ToolRegistry()
    registry.register(tool)
    return registry


def research_card(policy_decision_ids: list[str]) -> dict:
    """Return raw card input with policy decision IDs represented."""
    return {
        "schema_version": "1.2.1",
        "run_id": RUN_ID,
        "conclusion_level": "exploratory",
        "title": "Remote Shell Live Write Trap",
        "policy_decision_ids": policy_decision_ids,
    }


def scorecard(policy_decision_ids: list[str]) -> dict:
    """Return raw scorecard input that already represents policy deny IDs."""
    return {
        "schema_version": "1.2.1",
        "run_id": RUN_ID,
        "conclusion_level": "exploratory",
        "policy_decision_ids": policy_decision_ids,
        "metrics": {},
        "warnings": ["deny_barrier_verified"],
    }
