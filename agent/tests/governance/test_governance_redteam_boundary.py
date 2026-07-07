from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

from src.agent.tools import BaseTool, ToolRegistry
from src.governance.budget import BudgetManager, BudgetSnapshot
from src.governance.decisions import RuntimeContext
from src.governance.discovery import ManifestCache
from src.governance.errors import PolicyDenied
from src.governance.manifest import RiskLevel, ToolManifest, ToolSurface
from src.governance.policy_engine import PolicyEngine, PolicyRule
from src.governance.runtime import GovernedToolRegistry
from src.governance.trace_adapter import DecisionRecorder


class _ProbeTool(BaseTool):
    name = "redteam_probe"
    description = "redteam probe"
    parameters = {"type": "object", "properties": {}}
    repeatable = True
    is_readonly = False

    def __init__(self, *, delay_seconds: float = 0.0) -> None:
        self.calls = 0
        self.last_kwargs: dict[str, Any] = {}
        self._delay_seconds = delay_seconds
        self._lock = threading.Lock()

    def execute(self, **kwargs: Any) -> str:
        if self._delay_seconds:
            time.sleep(self._delay_seconds)
        with self._lock:
            self.calls += 1
            self.last_kwargs = dict(kwargs)
            calls = self.calls
        return json.dumps({"status": "ok", "calls": calls})


class _FailingRecorder(DecisionRecorder):
    def record(self, decision, *, manifest=None) -> None:
        del decision, manifest
        raise RuntimeError("trace unavailable")


def _manifest(risk: RiskLevel, *, surface: ToolSurface = ToolSurface.CLI) -> ToolManifest:
    return ToolManifest(
        name="redteam_probe",
        surface=surface,
        readonly=risk == RiskLevel.R0_READ,
        repeatable=True,
        risk_level=risk,
        requires_auth=False,
        requires_consent=risk == RiskLevel.R4_TRADE_WRITE,
        allowed_modes=["research", "paper", "advisory", "live"],
        secret_access="none",
        timeout_seconds=30,
        side_effects=["redteam"],
    )


def _registry(tool: _ProbeTool | None = None) -> tuple[ToolRegistry, _ProbeTool]:
    tool = tool or _ProbeTool()
    inner = ToolRegistry()
    inner.register(tool)
    return inner, tool


def _governed(
    *,
    risk: RiskLevel,
    context: RuntimeContext,
    tool: _ProbeTool | None = None,
    policy: PolicyEngine | None = None,
    recorder: DecisionRecorder | None = None,
    budget_manager: BudgetManager | None = None,
) -> tuple[GovernedToolRegistry, _ProbeTool]:
    inner, tool = _registry(tool)
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=ManifestCache({"redteam_probe": _manifest(risk, surface=context.surface)}, surface=context.surface),
        context=context,
        policy=policy,
        decision_recorder=recorder,
        budget_manager=budget_manager,
    )
    return governed, tool


def test_proxy_public_surface_does_not_expose_raw_tool_escape_hatch() -> None:
    governed, _tool = _governed(
        risk=RiskLevel.R4_TRADE_WRITE,
        context=RuntimeContext(surface=ToolSurface.CLI, mode="observe"),
    )

    proxy = governed.get("redteam_probe")

    assert not hasattr(proxy, "__dict__")
    assert not hasattr(proxy, "_raw_tool")
    assert getattr(proxy, "execute").__self__ is proxy
    with pytest.raises(PolicyDenied):
        proxy.execute(symbol="BTC", side="BUY")


def test_governance_off_cannot_downgrade_high_risk_execution() -> None:
    governed, tool = _governed(
        risk=RiskLevel.R5_SHELL,
        context=RuntimeContext(surface=ToolSurface.REMOTE_API, mode="off"),
    )

    with pytest.raises(PolicyDenied):
        governed.execute("redteam_probe", {})

    assert tool.calls == 0


def test_governance_off_preserves_low_risk_legacy_execution() -> None:
    governed, tool = _governed(
        risk=RiskLevel.R0_READ,
        context=RuntimeContext(surface=ToolSurface.MCP_STDIO, mode="off"),
    )

    result = json.loads(governed.execute("redteam_probe", {}))

    assert result["status"] == "ok"
    assert tool.calls == 1


def test_policy_predicate_cannot_mutate_raw_execution_params() -> None:
    def mutate_params(**kwargs: Any) -> bool:
        kwargs["params"]["nested"]["risk"] = "mutated"
        kwargs["params"]["injected_after_policy"] = True
        return False

    policy = PolicyEngine(
        rules=[
            PolicyRule(
                priority=1,
                rule_id="mutating-predicate",
                description="mutates params and does not match",
                action="allow",
                predicate=mutate_params,
            ),
            PolicyRule(priority=2, rule_id="allow", description="allow", action="allow"),
        ]
    )
    governed, tool = _governed(
        risk=RiskLevel.R0_READ,
        context=RuntimeContext(surface=ToolSurface.MCP_STDIO, mode="enforce"),
        policy=policy,
    )
    params = {"nested": {"risk": "original"}}

    governed.execute("redteam_probe", params)

    assert params == {"nested": {"risk": "original"}}
    assert tool.last_kwargs == {"nested": {"risk": "original"}}


def test_low_risk_trace_failure_is_explicit_and_does_not_execute() -> None:
    governed, tool = _governed(
        risk=RiskLevel.R1_WRITE_LOCAL,
        context=RuntimeContext(surface=ToolSurface.CLI, mode="observe"),
        recorder=_FailingRecorder(),
    )

    with pytest.raises(RuntimeError, match="trace unavailable"):
        governed.execute("redteam_probe", {})

    assert tool.calls == 0


def test_concurrent_budget_attack_cannot_exceed_limit() -> None:
    budget = BudgetManager(BudgetSnapshot(max_tool_calls=1))
    tool = _ProbeTool(delay_seconds=0.01)
    governed, tool = _governed(
        risk=RiskLevel.R1_WRITE_LOCAL,
        context=RuntimeContext(surface=ToolSurface.CLI, mode="observe"),
        tool=tool,
        budget_manager=budget,
    )
    barrier = threading.Barrier(12)
    results: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def call_tool() -> None:
        try:
            barrier.wait(timeout=5)
            result = governed.execute("redteam_probe", {})
            with lock:
                results.append(result)
        except BaseException as exc:  # noqa: BLE001 - test captures thread failures
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=call_tool) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert tool.calls == 1
    assert len(results) == 1
    assert sum(isinstance(exc, PolicyDenied) for exc in errors) == 11
