from __future__ import annotations

import json

from src.agent.loop import AgentLoop
from src.agent.tools import BaseTool
from src.governance.decisions import PolicyDecision
from src.governance.errors import PolicyDenied


class _ReadonlyTool(BaseTool):
    name = "blocked_read"
    description = "blocked"
    parameters = {"type": "object", "properties": {}}
    is_readonly = True

    def execute(self, **kwargs):
        return "{}"


class _DenyingRegistry:
    def __init__(self) -> None:
        self.tool = _ReadonlyTool()
        self.calls = 0

    def get(self, name: str):
        return self.tool

    def execute(self, name: str, params: dict):
        self.calls += 1
        decision = PolicyDecision(
            tool_name=name,
            action="deny",
            mode="enforce",
            reasons=["blocked by test"],
            rule_id="test",
        )
        raise PolicyDenied(decision, shadow=False)


class _DummyLLM:
    pass


def test_agent_loop_converts_policy_denied_to_tool_result() -> None:
    registry = _DenyingRegistry()
    agent = AgentLoop(registry=registry, llm=_DummyLLM())

    result, _elapsed_ms = agent._invoke_tool("blocked_read", {})
    payload = json.loads(result)

    assert registry.calls == 1
    assert payload["status"] == "error"
    assert payload["error_code"] == "policy_denied"
    assert payload["trace_status"] == "denied"
    assert "blocked by test" in payload["message"]
