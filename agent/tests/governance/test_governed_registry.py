from __future__ import annotations

import json

import pytest

from src.agent.tools import BaseTool, ToolRegistry
from src.governance.decisions import RuntimeContext
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

    def execute(self, **kwargs):
        self.calls += 1
        return json.dumps({"status": "ok", "calls": self.calls})


class _ReadTool(BaseTool):
    name = "new_read"
    description = "new read"
    parameters = {"type": "object", "properties": {}}
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs):
        return json.dumps({"status": "ok"})


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


def test_mode_off_delegates_directly() -> None:
    inner, tool = _registry()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=_cache(RiskLevel.R5_SHELL, surface=ToolSurface.REMOTE_API),
        context=RuntimeContext(surface=ToolSurface.REMOTE_API, mode="off"),
    )

    result = json.loads(governed.execute("counting", {}))

    assert result["calls"] == 1
    assert tool.calls == 1


def test_register_delegates_to_inner_registry_and_updates_manifest_cache() -> None:
    inner = ToolRegistry()
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=ManifestCache({}, surface=ToolSurface.MCP_STDIO),
        context=RuntimeContext(surface=ToolSurface.MCP_STDIO, mode="enforce"),
    )

    governed.register(_ReadTool())

    assert "new_read" in governed.tool_names
    assert governed.manifest_cache.get("new_read").risk_level == RiskLevel.R0_READ
    assert json.loads(governed.execute("new_read", {})) == {"status": "ok"}
