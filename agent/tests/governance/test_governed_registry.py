from __future__ import annotations

import json

import pytest

from src.agent.tools import BaseTool, ToolRegistry
from src.governance.budget import BudgetManager, BudgetSnapshot
from src.governance.decisions import RuntimeContext
from src.governance.decisions import build_param_audit
from src.governance.discovery import ManifestCache
from src.governance.errors import PolicyDenied
from src.governance.manifest import RiskLevel, ToolManifest, ToolSurface
from src.governance.runtime import GovernedToolRegistry
from src.governance.trace_adapter import DecisionRecorder


class _CountingTool(BaseTool):
    name = "counting"
    description = "counting"
    parameters = {"type": "object", "properties": {}}
    repeatable = True
    is_readonly = False

    def __init__(self) -> None:
        self.calls = 0
        self.last_kwargs = {}

    def execute(self, **kwargs):
        self.calls += 1
        self.last_kwargs = dict(kwargs)
        return json.dumps({"status": "ok", "calls": self.calls})


class _RemoteReadTool:
    name = "mcp_counting"
    description = "remote counting"
    parameters = {"type": "object", "properties": {}}
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs):
        return json.dumps({"status": "ok", "remote": True})


class _FailingRecorder(DecisionRecorder):
    def record(self, decision, *, manifest=None) -> None:
        del decision, manifest
        raise RuntimeError("trace unavailable")


def _registry(tool: _CountingTool | None = None) -> tuple[ToolRegistry, _CountingTool]:
    tool = tool or _CountingTool()
    inner = ToolRegistry()
    inner.register(tool)
    return inner, tool


def _cache(risk: RiskLevel, *, surface: ToolSurface = ToolSurface.CLI) -> ManifestCache:
    manifest = ToolManifest(
        name="counting",
        surface=surface,
        readonly=False,
        repeatable=True,
        risk_level=risk,
        requires_auth=False,
        requires_consent=risk == RiskLevel.R4_TRADE_WRITE,
        allowed_modes=["research", "paper", "advisory", "live"],
        secret_access="none",
        timeout_seconds=30,
        side_effects=["test"],
    )
    return ManifestCache({"counting": manifest}, surface=surface)


def test_r4_deny_shadow_denies_in_observe() -> None:
    inner, tool = _registry()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=_cache(RiskLevel.R4_TRADE_WRITE),
        context=RuntimeContext(surface=ToolSurface.CLI, mode="observe"),
    )

    with pytest.raises(PolicyDenied) as raised:
        governed.execute("counting", {})

    assert raised.value.shadow is True
    assert raised.value.trace_status == "skipped"
    assert tool.calls == 0


def test_get_execute_routes_through_governance() -> None:
    inner, tool = _registry()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=_cache(RiskLevel.R4_TRADE_WRITE),
        context=RuntimeContext(surface=ToolSurface.CLI, mode="observe"),
    )

    tool_proxy = governed.get("counting")

    with pytest.raises(PolicyDenied) as raised:
        tool_proxy.execute()

    assert raised.value.shadow is True
    assert tool.calls == 0


def test_governed_registry_does_not_expose_public_inner_registry() -> None:
    inner, _tool = _registry()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=_cache(RiskLevel.R4_TRADE_WRITE),
        context=RuntimeContext(surface=ToolSurface.CLI, mode="observe"),
    )

    assert not hasattr(governed, "inner")
    with pytest.raises(AttributeError):
        getattr(governed, "inner")


def test_r5_deny_shadow_denies_in_warn() -> None:
    inner, tool = _registry()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=_cache(RiskLevel.R5_SHELL, surface=ToolSurface.REMOTE_API),
        context=RuntimeContext(surface=ToolSurface.REMOTE_API, mode="warn"),
    )

    with pytest.raises(PolicyDenied) as raised:
        governed.execute("counting", {})

    assert raised.value.shadow is True
    assert tool.calls == 0


def test_policy_denied_does_not_call_inner_execute() -> None:
    inner, tool = _registry()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=_cache(RiskLevel.UNCLASSIFIED),
        context=RuntimeContext(surface=ToolSurface.CLI, mode="enforce"),
    )

    with pytest.raises(PolicyDenied):
        governed.execute("counting", {"password": "secret"})

    assert tool.calls == 0


def test_budget_exceeded_denies_before_inner_execute() -> None:
    inner, tool = _registry()
    budget = BudgetManager(BudgetSnapshot(max_tool_calls=0))
    recorder = DecisionRecorder()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=_cache(RiskLevel.R1_WRITE_LOCAL),
        context=RuntimeContext(surface=ToolSurface.CLI, mode="observe"),
        decision_recorder=recorder,
        budget_manager=budget,
    )

    with pytest.raises(PolicyDenied) as raised:
        governed.execute("counting", {})

    assert raised.value.decision.rule_id == "budget_exceeded"
    assert tool.calls == 0
    assert budget.snapshot.tool_calls == 1
    assert recorder.decisions[-1].rule_id == "budget_exceeded"


def test_trace_write_failure_denies_high_risk_before_inner_execute() -> None:
    inner, tool = _registry()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=_cache(RiskLevel.R4_TRADE_WRITE),
        context=RuntimeContext(surface=ToolSurface.CLI, mode="observe"),
        decision_recorder=_FailingRecorder(),
    )

    with pytest.raises(PolicyDenied) as raised:
        governed.execute("counting", {})

    assert raised.value.decision.rule_id == "trace_record_failed"
    assert raised.value.shadow is True
    assert tool.calls == 0


def test_low_risk_deny_observe_continues_with_warning() -> None:
    inner, tool = _registry()
    recorder = DecisionRecorder()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=_cache(RiskLevel.R1_WRITE_LOCAL),
        context=RuntimeContext(surface=ToolSurface.CLI, mode="observe"),
        decision_recorder=recorder,
    )

    result = json.loads(governed.execute("counting", {}))

    assert result["status"] == "ok"
    assert tool.calls == 1
    assert recorder.decisions[-1].action == "deny"


def test_warn_mode_records_visible_warning_when_continuing() -> None:
    inner, tool = _registry()
    recorder = DecisionRecorder()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=_cache(RiskLevel.R1_WRITE_LOCAL),
        context=RuntimeContext(surface=ToolSurface.CLI, mode="warn"),
        decision_recorder=recorder,
    )

    result = json.loads(governed.execute("counting", {}))

    assert result["status"] == "ok"
    assert tool.calls == 1
    assert any(record["type"] == "policy_warning" for record in recorder.records)


def test_policy_decision_goes_to_trace() -> None:
    inner, _tool = _registry()
    recorder = DecisionRecorder()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=_cache(RiskLevel.R1_WRITE_LOCAL),
        context=RuntimeContext(surface=ToolSurface.CLI, mode="observe"),
        decision_recorder=recorder,
    )

    governed.execute("counting", {"api_key": "secret"})

    record = recorder.records[-1]
    assert record["type"] == "policy_decision"
    assert record["decision"]["tool_name"] == "counting"
    assert "params_hash" in record["decision"]
    assert "secret" not in json.dumps(record, ensure_ascii=False)


def test_policy_hash_matches_actual_executed_params() -> None:
    inner, tool = _registry()
    recorder = DecisionRecorder()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=_cache(RiskLevel.R1_WRITE_LOCAL),
        context=RuntimeContext(surface=ToolSurface.CLI, mode="observe"),
        decision_recorder=recorder,
    )
    params = {"symbol": "AAPL", "api_key": "secret"}

    governed.execute("counting", params)

    assert tool.last_kwargs == params
    assert recorder.decisions[-1].params_hash == build_param_audit(tool.last_kwargs).params_hash


def test_mode_off_delegates_low_risk_directly() -> None:
    inner, tool = _registry()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=_cache(RiskLevel.R0_READ, surface=ToolSurface.MCP_STDIO),
        context=RuntimeContext(surface=ToolSurface.MCP_STDIO, mode="off"),
    )

    result = json.loads(governed.execute("counting", {}))

    assert result["calls"] == 1
    assert tool.calls == 1


def test_register_preserves_tool_registry_surface_and_manifest() -> None:
    inner = ToolRegistry()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=ManifestCache({}, surface=ToolSurface.SWARM),
        context=RuntimeContext(surface=ToolSurface.SWARM, mode="observe"),
    )

    governed.register(_RemoteReadTool())

    assert "mcp_counting" in governed
    proxy = governed.get("mcp_counting")
    assert proxy is not inner.get("mcp_counting")
    assert isinstance(proxy, _RemoteReadTool)
    assert proxy.name == "mcp_counting"
    assert proxy.description == "remote counting"
    assert governed.manifest_cache.get("mcp_counting").risk_level == RiskLevel.R2_NETWORK
