"""Red-team tests for governed registry raw-tool escape paths."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.agent.tools import BaseTool, ToolRegistry
from src.governance.decision_recorder import DecisionRecorder
from src.governance.decisions import PolicyDecision
from src.governance.runtime import (
    GovernedToolRegistry,
    PolicyDenied,
    RuntimeContext,
)


class CountingTool(BaseTool):
    name = "fake_shell"
    description = "counted red-team tool"
    parameters = {"type": "object", "properties": {}}
    risk_level = "R5_SHELL"
    is_readonly = False

    def __init__(self) -> None:
        self.execution_counter = 0

    def execute(self, **kwargs: Any) -> str:
        self.execution_counter += 1
        return json.dumps({"status": "ok", "kwargs": kwargs}, ensure_ascii=False)


class StaticPolicy:
    def __init__(self, action: str = "deny") -> None:
        self.action = action

    def evaluate(self, *, name: str, params: dict[str, Any], manifest: Any, context: RuntimeContext) -> PolicyDecision:
        del params, context
        return PolicyDecision(
            tool_name=name,
            action=self.action,  # type: ignore[arg-type]
            risk_level=manifest.risk_level,
            reasons=[f"{manifest.risk_level} test decision"],
            reason_codes=[f"{manifest.risk_level}_{self.action.upper()}"],
            policy_engine_version="redteam-test",
        )


class FailingRecorder(DecisionRecorder):
    def record_best_effort(self, envelope):  # type: ignore[no-untyped-def]
        raise RuntimeError("recorder down")


def _governed(tool: CountingTool, *, mode: str = "warn", policy_action: str = "deny") -> GovernedToolRegistry:
    registry = ToolRegistry()
    registry.register(tool)
    return GovernedToolRegistry(
        registry,
        policy=StaticPolicy(policy_action),
        decision_recorder=DecisionRecorder(artifact_store=None),
        context=RuntimeContext(mode=mode, surface="remote_api", run_id="run_redteam"),
    )


def test_get_execute_routes_through_governance_for_r5_shell() -> None:
    tool = CountingTool()
    governed = _governed(tool)

    proxy = governed.get("fake_shell")
    assert proxy is not None
    with pytest.raises(PolicyDenied):
        proxy.execute(cmd="whoami")

    assert tool.execution_counter == 0


def test_get_execute_routes_through_governance_for_r4_trade_write() -> None:
    tool = CountingTool()
    tool.name = "fake_trade_write"
    tool.risk_level = "R4_TRADE_WRITE"
    governed = _governed(tool)

    proxy = governed.get("fake_trade_write")
    assert proxy is not None
    with pytest.raises(PolicyDenied):
        proxy.execute(symbol="AAPL", quantity=1)

    assert tool.execution_counter == 0


def test_public_inner_attribute_is_not_available() -> None:
    governed = _governed(CountingTool())
    assert not hasattr(governed, "inner")


def test_proxy_does_not_expose_raw_tool_private_members() -> None:
    tool = CountingTool()
    governed = _governed(tool)
    proxy = governed.get("fake_shell")

    assert proxy is not None
    assert not hasattr(proxy, "_tool")
    assert not hasattr(proxy, "_raw_tool")
    assert not hasattr(proxy, "__wrapped__")


def test_direct_raw_tool_escape_is_not_available_from_routes() -> None:
    from src.governance.route_coverage import build_governed_tool_registry

    tool = CountingTool()
    registry = ToolRegistry()
    registry.register(tool)
    governed = build_governed_tool_registry(registry, surface="remote_api", mode="warn")

    exposed = governed.get("fake_shell")
    assert exposed is not tool


def test_warn_mode_high_risk_shadow_deny_execution_counter_zero() -> None:
    tool = CountingTool()
    governed = _governed(tool, mode="warn")

    with pytest.raises(PolicyDenied) as exc_info:
        governed.execute("fake_shell", {"cmd": "id"})

    assert tool.execution_counter == 0
    assert exc_info.value.envelope.shadow_deny is True
    assert exc_info.value.envelope.inner_tool_executed is False


def test_observe_mode_high_risk_shadow_deny_execution_counter_zero() -> None:
    tool = CountingTool()
    governed = _governed(tool, mode="observe")

    with pytest.raises(PolicyDenied):
        governed.execute("fake_shell", {"cmd": "id"})

    assert tool.execution_counter == 0


def test_policy_denied_payload_malformed_does_not_allow_execution() -> None:
    from src.agent.loop import _is_tool_success

    assert _is_tool_success('{"status": "error", "error_code": "policy_denied"') is False


def test_budget_exceeded_blocks_before_raw_execution() -> None:
    tool = CountingTool()
    tool.name = "fake_trade_write"
    tool.risk_level = "R4_TRADE_WRITE"
    registry = ToolRegistry()
    registry.register(tool)
    governed = GovernedToolRegistry(
        registry,
        policy=StaticPolicy("allow"),
        decision_recorder=DecisionRecorder(artifact_store=None),
        context=RuntimeContext(
            mode="warn",
            surface="live_connector",
            run_id="run_budget",
            budget_state={"remaining_notional": 0, "requested_notional": 10_000},
        ),
    )

    with pytest.raises(PolicyDenied):
        governed.execute("fake_trade_write", {"symbol": "AAPL", "notional": 10_000})

    assert tool.execution_counter == 0


def test_trace_recorder_failure_fail_closed_for_high_risk() -> None:
    tool = CountingTool()
    registry = ToolRegistry()
    registry.register(tool)
    governed = GovernedToolRegistry(
        registry,
        policy=StaticPolicy("deny"),
        decision_recorder=FailingRecorder(artifact_store=None),
        context=RuntimeContext(mode="warn", surface="remote_api", run_id="run_recorder_down"),
    )

    with pytest.raises(PolicyDenied):
        governed.execute("fake_shell", {"cmd": "id"})

    assert tool.execution_counter == 0
