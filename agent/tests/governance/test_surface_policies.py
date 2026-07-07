from __future__ import annotations

import json

from src.agent.tools import BaseTool, ToolRegistry
from src.governance.decisions import RuntimeContext
from src.governance.discovery import ManifestCache
from src.governance.manifest import RiskLevel, ToolManifest, ToolSurface
from src.governance.policy_engine import PolicyEngine
from src.governance.runtime import GovernedToolRegistry


class _LiveGuardStillRunsTool(BaseTool):
    name = "trading_place_order"
    description = "live guard placeholder"
    parameters = {"type": "object", "properties": {"symbol": {"type": "string"}}}
    is_readonly = False
    repeatable = False

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, **kwargs):
        self.calls += 1
        return json.dumps({"status": "blocked", "reason": "live guard denied"})


def _manifest(
    *,
    name: str = "tool",
    surface: ToolSurface = ToolSurface.CLI,
    risk: RiskLevel = RiskLevel.R0_READ,
    readonly: bool = True,
    live_classification: str | None = None,
) -> ToolManifest:
    return ToolManifest(
        name=name,
        surface=surface,
        readonly=readonly,
        repeatable=True,
        risk_level=risk,
        requires_auth=False,
        requires_consent=risk == RiskLevel.R4_TRADE_WRITE,
        allowed_modes=["research", "paper", "advisory", "live"],
        secret_access="none",
        timeout_seconds=30,
        side_effects=[],
        live_classification=live_classification,
    )


def test_connector_unknown_fail_closed() -> None:
    decision = PolicyEngine().evaluate(
        name="mcp_robinhood_new_order_tool",
        params={},
        manifest=_manifest(
            name="mcp_robinhood_new_order_tool",
            surface=ToolSurface.LIVE_CONNECTOR,
            risk=RiskLevel.R4_TRADE_WRITE,
            readonly=False,
            live_classification="UNKNOWN",
        ),
        context=RuntimeContext(surface=ToolSurface.LIVE_CONNECTOR, mode="enforce"),
    )

    assert decision.action == "deny"
    assert decision.rule_id == "P10"


def test_scheduler_denies_live_write() -> None:
    decision = PolicyEngine().evaluate(
        name="trading_place_order",
        params={},
        manifest=_manifest(
            name="trading_place_order",
            surface=ToolSurface.SCHEDULER,
            risk=RiskLevel.R4_TRADE_WRITE,
            readonly=False,
        ),
        context=RuntimeContext(surface=ToolSurface.SCHEDULER, mode="enforce"),
    )

    assert decision.action == "deny"
    assert decision.rule_id == "P30"


def test_swarm_cannot_inject_mcp_url_via_prompt() -> None:
    decision = PolicyEngine().evaluate(
        name="run_swarm",
        params={"external_mcp_url_from_prompt": True},
        manifest=_manifest(
            name="run_swarm",
            surface=ToolSurface.SWARM,
            risk=RiskLevel.R1_WRITE_LOCAL,
            readonly=False,
        ),
        context=RuntimeContext(surface=ToolSurface.SWARM, mode="enforce"),
    )

    assert decision.action == "deny"
    assert decision.rule_id == "P35"


def test_r4_requires_live_guard_but_does_not_replace_it() -> None:
    engine = PolicyEngine()
    manifest = _manifest(
        name="trading_place_order",
        surface=ToolSurface.LIVE_CONNECTOR,
        risk=RiskLevel.R4_TRADE_WRITE,
        readonly=False,
    )
    decision = engine.evaluate(
        name="trading_place_order",
        params={},
        manifest=manifest,
        context=RuntimeContext(
            surface=ToolSurface.LIVE_CONNECTOR,
            mode="enforce",
            live_state={
                "mandate_active": True,
                "kill_switch_clear": True,
                "explicit_user_consent": True,
                "live_order_guard": True,
                "connector_profile_selected": True,
            },
        ),
    )
    assert decision.action == "allow"
    assert "live_order_guard" in decision.required_checks

    tool = _LiveGuardStillRunsTool()
    inner = ToolRegistry()
    inner.register(tool)
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=ManifestCache({"trading_place_order": manifest}, surface=ToolSurface.LIVE_CONNECTOR),
        context=RuntimeContext(
            surface=ToolSurface.LIVE_CONNECTOR,
            mode="enforce",
            live_state={
                "mandate_active": True,
                "kill_switch_clear": True,
                "explicit_user_consent": True,
                "live_order_guard": True,
                "connector_profile_selected": True,
            },
        ),
    )

    result = json.loads(governed.execute("trading_place_order", {"symbol": "AAPL"}))

    assert tool.calls == 1
    assert result["status"] == "blocked"
    assert result["reason"] == "live guard denied"


def test_local_no_network_fallback_denies() -> None:
    decision = PolicyEngine().evaluate(
        name="get_market_data",
        params={"explicit_local": True, "fallback_to_network": True},
        manifest=_manifest(
            name="get_market_data",
            surface=ToolSurface.CLI,
            risk=RiskLevel.R2_NETWORK,
        ),
        context=RuntimeContext(surface=ToolSurface.CLI, mode="enforce"),
    )

    assert decision.action == "deny"
    assert decision.rule_id == "P50"
