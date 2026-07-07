"""Tool governance policy engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from src.governance.decisions import PolicyAction, PolicyDecision, RuntimeContext, build_param_audit
from src.governance.manifest import RiskLevel, ToolManifest, ToolSurface


Predicate = Callable[..., bool]
RuleAction = Literal["allow", "warn", "deny", "allow_if_all"]


@dataclass(frozen=True)
class PolicyRule:
    """One first-match governance rule."""

    priority: int
    rule_id: str
    description: str
    action: RuleAction
    surfaces: set[ToolSurface] | None = None
    risk_levels: set[RiskLevel] | None = None
    tool_names: set[str] | None = None
    predicate: Predicate | None = None
    required_checks: tuple[str, ...] = ()

    def matches(
        self,
        *,
        name: str,
        params: dict[str, Any],
        manifest: ToolManifest,
        context: RuntimeContext,
    ) -> bool:
        if self.surfaces is not None and context.surface not in self.surfaces:
            return False
        if self.risk_levels is not None and manifest.risk_level not in self.risk_levels:
            return False
        if self.tool_names is not None and name not in self.tool_names:
            return False
        if self.predicate is not None:
            return bool(self.predicate(name=name, params=params, manifest=manifest, context=context))
        return True


class PolicyEngine:
    """Evaluate tool calls by priority, with first-match wins."""

    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self.rules = sorted(rules if rules is not None else _builtin_rules(), key=lambda rule: rule.priority)

    def evaluate(
        self,
        *,
        name: str,
        params: dict[str, Any],
        manifest: ToolManifest,
        context: RuntimeContext,
    ) -> PolicyDecision:
        audit = build_param_audit(params)
        try:
            for rule in self.rules:
                if not rule.matches(name=name, params=params, manifest=manifest, context=context):
                    continue
                return self._decision_for_rule(
                    rule,
                    name=name,
                    manifest=manifest,
                    context=context,
                    params_hash=audit.params_hash,
                    params_preview=audit.preview,
                )
            return _decision(
                name=name,
                action="deny",
                context=context,
                rule_id="no_match",
                reasons=["No governance policy rule matched; fail-safe deny"],
                params_hash=audit.params_hash,
                params_preview=audit.preview,
            )
        except Exception as exc:  # noqa: BLE001 - policy exceptions must fail safe
            action: PolicyAction = "deny" if _must_fail_closed(manifest, context) else "warn"
            return _decision(
                name=name,
                action=action,
                context=context,
                rule_id="policy_exception",
                reasons=[f"PolicyEngine exception handled fail-safe: {exc.__class__.__name__}"],
                params_hash=audit.params_hash,
                params_preview=audit.preview,
            )

    def _decision_for_rule(
        self,
        rule: PolicyRule,
        *,
        name: str,
        manifest: ToolManifest,
        context: RuntimeContext,
        params_hash: str,
        params_preview: dict[str, Any],
    ) -> PolicyDecision:
        if rule.action == "allow_if_all":
            missing = [check for check in rule.required_checks if not _check_state(context, check)]
            if missing:
                return _decision(
                    name=name,
                    action="deny",
                    context=context,
                    rule_id=rule.rule_id,
                    reasons=[f"{rule.description}; missing required checks: {', '.join(missing)}"],
                    required_checks=list(rule.required_checks),
                    params_hash=params_hash,
                    params_preview=params_preview,
                )
            return _decision(
                name=name,
                action="allow",
                context=context,
                rule_id=rule.rule_id,
                reasons=[rule.description],
                required_checks=list(rule.required_checks),
                params_hash=params_hash,
                params_preview=params_preview,
            )

        action: PolicyAction
        if rule.rule_id == "P900":
            action = "deny" if context.mode == "enforce" else "warn"
        else:
            action = rule.action  # type: ignore[assignment]
        return _decision(
            name=name,
            action=action,
            context=context,
            rule_id=rule.rule_id,
            reasons=[rule.description],
            required_checks=list(rule.required_checks),
            params_hash=params_hash,
            params_preview=params_preview,
        )


def _builtin_rules() -> list[PolicyRule]:
    return [
        PolicyRule(
            priority=10,
            rule_id="P10",
            description="UNKNOWN live connector tool is fail-closed",
            action="deny",
            surfaces={ToolSurface.LIVE_CONNECTOR},
            predicate=lambda **kw: getattr(kw["manifest"], "live_classification", None) == "UNKNOWN",
        ),
        PolicyRule(
            priority=20,
            rule_id="P20",
            description="Remote API, MCP SSE/HTTP, and channel bots cannot execute shell tools by default",
            action="deny",
            surfaces={ToolSurface.REMOTE_API, ToolSurface.MCP_SSE, ToolSurface.MCP_HTTP, ToolSurface.CHANNEL_BOT},
            risk_levels={RiskLevel.R5_SHELL},
        ),
        PolicyRule(
            priority=30,
            rule_id="P30",
            description="Scheduler cannot execute live write or shell tools by default",
            action="deny",
            surfaces={ToolSurface.SCHEDULER},
            risk_levels={RiskLevel.R4_TRADE_WRITE, RiskLevel.R5_SHELL},
        ),
        PolicyRule(
            priority=35,
            rule_id="P35",
            description="Swarm workers cannot receive external MCP URLs from prompt input",
            action="deny",
            surfaces={ToolSurface.SWARM},
            predicate=lambda **kw: bool(kw["params"].get("external_mcp_url_from_prompt")),
        ),
        PolicyRule(
            priority=40,
            rule_id="P40",
            description="Live trade writes require mandate, clear kill switch, explicit consent, live guard, and connector profile",
            action="allow_if_all",
            risk_levels={RiskLevel.R4_TRADE_WRITE},
            required_checks=(
                "mandate_active",
                "kill_switch_clear",
                "explicit_user_consent",
                "live_order_guard",
                "connector_profile_selected",
            ),
        ),
        PolicyRule(
            priority=50,
            rule_id="P50",
            description="Explicit local market data requests cannot silently fall back to network",
            action="deny",
            tool_names={"get_market_data"},
            predicate=lambda **kw: bool(kw["params"].get("explicit_local"))
            and bool(kw["params"].get("fallback_to_network")),
        ),
        PolicyRule(
            priority=100,
            rule_id="P100",
            description="Read-only MCP stdio R0 tool allowed by default",
            action="allow",
            surfaces={ToolSurface.MCP_STDIO},
            risk_levels={RiskLevel.R0_READ},
            predicate=lambda **kw: bool(kw["manifest"].readonly),
        ),
        PolicyRule(
            priority=900,
            rule_id="P900",
            description="Unclassified tools require observation/manual review before enforcement",
            action="warn",
            risk_levels={RiskLevel.UNCLASSIFIED},
        ),
        PolicyRule(
            priority=999,
            rule_id="P999",
            description="No matching governance rule; fail-safe deny",
            action="deny",
        ),
    ]


def _decision(
    *,
    name: str,
    action: PolicyAction,
    context: RuntimeContext,
    rule_id: str,
    reasons: list[str],
    params_hash: str,
    params_preview: dict[str, Any],
    required_checks: list[str] | None = None,
) -> PolicyDecision:
    return PolicyDecision(
        tool_name=name,
        action=action,
        mode=context.mode,
        reasons=reasons,
        required_checks=required_checks or [],
        rule_id=rule_id,
        params_hash=params_hash,
        params_preview=params_preview,
    )


def _check_state(context: RuntimeContext, check: str) -> bool:
    if check in context.live_state:
        return bool(context.live_state[check])
    if check in context.user_auth_state:
        return bool(context.user_auth_state[check])
    if check in context.budget_state:
        return bool(context.budget_state[check])
    return False


def _must_fail_closed(manifest: ToolManifest, context: RuntimeContext) -> bool:
    return manifest.risk_level in {RiskLevel.R4_TRADE_WRITE, RiskLevel.R5_SHELL} or context.surface in {
        ToolSurface.REMOTE_API,
        ToolSurface.MCP_SSE,
        ToolSurface.MCP_HTTP,
        ToolSurface.SWARM,
        ToolSurface.SCHEDULER,
        ToolSurface.LIVE_CONNECTOR,
        ToolSurface.CHANNEL_BOT,
    }
