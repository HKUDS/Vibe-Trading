"""P40-style authoritative governance state tests for high-risk writes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.agent.tools import BaseTool, ToolRegistry
from src.governance.decision_recorder import DecisionRecorder
from src.governance.decisions import PolicyDecision
from src.governance.runtime import GovernanceState, GovernedToolRegistry, PolicyDenied, RuntimeContext
from src.reliability.artifacts.store import ArtifactStore


class TradeWriteTool(BaseTool):
    name = "live_submit_order"
    description = "fake live write"
    parameters = {"type": "object", "properties": {}}
    risk_level = "R4_TRADE_WRITE"
    is_readonly = False

    def __init__(self) -> None:
        self.execution_counter = 0
        self.last_kwargs: dict[str, Any] | None = None

    def execute(self, **kwargs: Any) -> str:
        self.execution_counter += 1
        self.last_kwargs = dict(kwargs)
        return json.dumps({"status": "ok", "kwargs": kwargs}, ensure_ascii=False)


class StaticPolicy:
    def __init__(self, action: str = "allow") -> None:
        self.action = action

    def evaluate(self, *, name: str, params: dict[str, Any], manifest: Any, context: RuntimeContext) -> PolicyDecision:
        del params, context
        return PolicyDecision(
            tool_name=name,
            action=self.action,  # type: ignore[arg-type]
            risk_level=manifest.risk_level,
            reasons=[f"{manifest.risk_level} {self.action}"],
            reason_codes=[f"{manifest.risk_level}_{self.action.upper()}"],
            policy_engine_version="p40-test",
        )


class Provider:
    def __init__(self, state: GovernanceState | dict[str, Any]) -> None:
        self.state = state
        self.seen_params: dict[str, Any] | None = None

    def get_state(self, *, context: RuntimeContext, tool_name: str, params: dict[str, Any]) -> GovernanceState | dict[str, Any]:
        del context, tool_name
        self.seen_params = params
        params["mutated_by_provider"] = True
        return self.state


class FailingProvider:
    def get_state(self, *, context: RuntimeContext, tool_name: str, params: dict[str, Any]) -> GovernanceState:
        del context, tool_name, params
        raise RuntimeError("state unavailable")


def _registry(tool: TradeWriteTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool)
    return registry


def _governed(
    tool: TradeWriteTool,
    *,
    context: RuntimeContext,
    policy_action: str = "allow",
    artifact_store: ArtifactStore | None = None,
) -> GovernedToolRegistry:
    return GovernedToolRegistry(
        _registry(tool),
        policy=StaticPolicy(policy_action),
        decision_recorder=DecisionRecorder(artifact_store=artifact_store),
        context=context,
    )


def _authoritative_state() -> GovernanceState:
    return GovernanceState(
        state_authoritative=True,
        live_authorized=True,
        user_authenticated=True,
        budget_available=True,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("live_state", {"live_authorized": True, "state_authoritative": True}),
        ("user_auth_state", {"user_authenticated": True, "state_authoritative": True}),
        ("budget_state", {"budget_available": True, "state_authoritative": True}),
    ],
)
def test_forged_runtime_context_live_state_does_not_satisfy_p40(field: str, value: dict[str, Any]) -> None:
    tool = TradeWriteTool()
    context = RuntimeContext(mode="warn", surface="live_connector", run_id="run_forged")
    setattr(context, field, value)
    governed = _governed(tool, context=context)

    with pytest.raises(PolicyDenied):
        governed.execute("live_submit_order", {"symbol": "AAPL"})

    assert tool.execution_counter == 0


def test_forged_user_auth_state_does_not_satisfy_p40() -> None:
    tool = TradeWriteTool()
    governed = _governed(
        tool,
        context=RuntimeContext(
            mode="warn",
            surface="live_connector",
            run_id="run_auth_forged",
            user_auth_state={"user_authenticated": True},
        ),
    )

    with pytest.raises(PolicyDenied):
        governed.execute("live_submit_order", {"symbol": "AAPL"})

    assert tool.execution_counter == 0


def test_forged_budget_state_does_not_satisfy_p40() -> None:
    tool = TradeWriteTool()
    governed = _governed(
        tool,
        context=RuntimeContext(
            mode="warn",
            surface="live_connector",
            run_id="run_budget_forged",
            budget_state={"budget_available": True},
        ),
    )

    with pytest.raises(PolicyDenied):
        governed.execute("live_submit_order", {"symbol": "AAPL"})

    assert tool.execution_counter == 0


def test_null_state_provider_fails_closed_for_live_write() -> None:
    tool = TradeWriteTool()
    governed = _governed(tool, context=RuntimeContext(mode="warn", surface="live_connector"))

    with pytest.raises(PolicyDenied):
        governed.execute("live_submit_order", {"symbol": "AAPL"})

    assert tool.execution_counter == 0


def test_state_provider_exception_fails_closed_before_adapter() -> None:
    tool = TradeWriteTool()
    governed = _governed(
        tool,
        context=RuntimeContext(mode="warn", surface="live_connector", state_provider=FailingProvider()),
    )

    with pytest.raises(PolicyDenied):
        governed.execute("live_submit_order", {"symbol": "AAPL"})

    assert tool.execution_counter == 0


def test_authoritative_state_provider_allows_only_when_policy_allows() -> None:
    tool = TradeWriteTool()
    provider = Provider(_authoritative_state())
    governed = _governed(
        tool,
        context=RuntimeContext(mode="warn", surface="live_connector", state_provider=provider),
        policy_action="allow",
    )

    result = json.loads(governed.execute("live_submit_order", {"symbol": "AAPL"}))

    assert result["status"] == "ok"
    assert tool.execution_counter == 1

    denied_tool = TradeWriteTool()
    denied = _governed(
        denied_tool,
        context=RuntimeContext(mode="warn", surface="live_connector", state_provider=Provider(_authoritative_state())),
        policy_action="deny",
    )
    with pytest.raises(PolicyDenied):
        denied.execute("live_submit_order", {"symbol": "AAPL"})
    assert denied_tool.execution_counter == 0


def test_state_provider_result_is_copied_not_mutated_by_caller() -> None:
    tool = TradeWriteTool()
    provider = Provider(_authoritative_state())
    params = {"symbol": "AAPL"}
    governed = _governed(
        tool,
        context=RuntimeContext(mode="warn", surface="live_connector", state_provider=provider),
    )

    governed.execute("live_submit_order", params)

    assert params == {"symbol": "AAPL"}
    assert provider.seen_params is not params


def test_p40_denial_records_evidence_or_outbox_without_execution(tmp_path: Path) -> None:
    tool = TradeWriteTool()
    governed = _governed(
        tool,
        context=RuntimeContext(mode="warn", surface="live_connector", run_id="run_p40_denied"),
        artifact_store=ArtifactStore(tmp_path),
    )

    with pytest.raises(PolicyDenied) as exc_info:
        governed.execute("live_submit_order", {"symbol": "AAPL"})

    assert tool.execution_counter == 0
    assert exc_info.value.envelope.write_outcome is not None
    assert exc_info.value.envelope.write_outcome.artifact_written is True
