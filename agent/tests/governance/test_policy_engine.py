from __future__ import annotations

from src.governance.decisions import RuntimeContext
from src.governance.manifest import RiskLevel, ToolManifest, ToolSurface
from src.governance.policy_engine import PolicyEngine, PolicyRule


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
        requires_consent=False,
        allowed_modes=["research", "paper", "advisory"],
        secret_access="none",
        timeout_seconds=30,
        side_effects=[],
        live_classification=live_classification,
    )


def _ctx(surface: ToolSurface, mode: str = "enforce", **extra) -> RuntimeContext:
    return RuntimeContext(surface=surface, mode=mode, **extra)


def test_remote_api_denies_r5_shell() -> None:
    decision = PolicyEngine().evaluate(
        name="bash",
        params={},
        manifest=_manifest(name="bash", surface=ToolSurface.REMOTE_API, risk=RiskLevel.R5_SHELL, readonly=False),
        context=_ctx(ToolSurface.REMOTE_API),
    )

    assert decision.action == "deny"
    assert decision.rule_id == "P20"


def test_channel_bot_denies_r5_shell() -> None:
    decision = PolicyEngine().evaluate(
        name="bash",
        params={},
        manifest=_manifest(name="bash", surface=ToolSurface.CHANNEL_BOT, risk=RiskLevel.R5_SHELL, readonly=False),
        context=_ctx(ToolSurface.CHANNEL_BOT),
    )

    assert decision.action == "deny"
    assert decision.rule_id == "P20"


def test_mcp_sse_stricter_than_stdio() -> None:
    engine = PolicyEngine()

    stdio_read = engine.evaluate(
        name="read_file",
        params={},
        manifest=_manifest(name="read_file", surface=ToolSurface.MCP_STDIO, risk=RiskLevel.R0_READ),
        context=_ctx(ToolSurface.MCP_STDIO),
    )
    sse_shell = engine.evaluate(
        name="bash",
        params={},
        manifest=_manifest(name="bash", surface=ToolSurface.MCP_SSE, risk=RiskLevel.R5_SHELL, readonly=False),
        context=_ctx(ToolSurface.MCP_SSE),
    )

    assert stdio_read.action == "allow"
    assert stdio_read.rule_id == "P100"
    assert sse_shell.action == "deny"
    assert sse_shell.rule_id == "P20"


def test_unknown_tool_enforce_denies() -> None:
    decision = PolicyEngine().evaluate(
        name="brand_new",
        params={},
        manifest=_manifest(name="brand_new", risk=RiskLevel.UNCLASSIFIED, readonly=False),
        context=_ctx(ToolSurface.CLI, mode="enforce"),
    )

    assert decision.action == "deny"
    assert decision.rule_id == "P900"


def test_unknown_tool_observe_warns() -> None:
    decision = PolicyEngine().evaluate(
        name="brand_new",
        params={},
        manifest=_manifest(name="brand_new", risk=RiskLevel.UNCLASSIFIED, readonly=False),
        context=_ctx(ToolSurface.CLI, mode="observe"),
    )

    assert decision.action == "warn"
    assert decision.rule_id == "P900"


def test_policy_priority_specific_before_broad() -> None:
    broad_deny = PolicyRule(
        priority=100,
        rule_id="broad-deny",
        description="deny all R2",
        action="deny",
        risk_levels={RiskLevel.R2_NETWORK},
    )
    specific_allow = PolicyRule(
        priority=10,
        rule_id="specific-allow",
        description="allow one safe network tool",
        action="allow",
        tool_names={"safe_network_read"},
        risk_levels={RiskLevel.R2_NETWORK},
    )
    decision = PolicyEngine(rules=[broad_deny, specific_allow]).evaluate(
        name="safe_network_read",
        params={},
        manifest=_manifest(name="safe_network_read", risk=RiskLevel.R2_NETWORK),
        context=_ctx(ToolSurface.CLI),
    )

    assert decision.action == "allow"
    assert decision.rule_id == "specific-allow"


def test_no_matching_rule_fail_safe_deny() -> None:
    decision = PolicyEngine().evaluate(
        name="write_file",
        params={},
        manifest=_manifest(name="write_file", risk=RiskLevel.R1_WRITE_LOCAL, readonly=False),
        context=_ctx(ToolSurface.CLI, mode="enforce"),
    )

    assert decision.action == "deny"
    assert decision.rule_id == "P999"


def test_policy_engine_exception_high_risk_denies() -> None:
    def raises(**kwargs):
        raise RuntimeError("boom")

    decision = PolicyEngine(
        rules=[
            PolicyRule(
                priority=1,
                rule_id="raising",
                description="raise",
                action="allow",
                predicate=raises,
            )
        ]
    ).evaluate(
        name="bash",
        params={},
        manifest=_manifest(name="bash", risk=RiskLevel.R5_SHELL, readonly=False),
        context=_ctx(ToolSurface.REMOTE_API),
    )

    assert decision.action == "deny"
    assert decision.rule_id == "policy_exception"
