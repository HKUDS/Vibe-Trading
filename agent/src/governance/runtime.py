"""Runtime wrapper around the existing ToolRegistry."""

from __future__ import annotations

from typing import Any

from src.governance.config import get_governance_mode
from src.governance.decisions import PolicyDecision, RuntimeContext, build_param_audit
from src.governance.discovery import ManifestCache
from src.governance.errors import PolicyDenied
from src.governance.manifest import RiskLevel, ToolSurface
from src.governance.policy_engine import PolicyEngine
from src.governance.trace_adapter import DecisionRecorder


HIGH_RISK_DENY = {RiskLevel.R4_TRADE_WRITE, RiskLevel.R5_SHELL}


class GovernedToolRegistry:
    """Policy wrapper that preserves the existing ToolRegistry surface."""

    def __init__(
        self,
        inner: Any,
        *,
        manifest_cache: ManifestCache,
        policy: PolicyEngine | None = None,
        context: RuntimeContext | None = None,
        decision_recorder: DecisionRecorder | None = None,
    ) -> None:
        self.inner = inner
        self.manifest_cache = manifest_cache
        self.policy = policy or PolicyEngine()
        self.context = context or RuntimeContext(surface=manifest_cache.surface, mode=get_governance_mode())
        self.decision_recorder = decision_recorder or DecisionRecorder()

    @property
    def tool_names(self) -> list[str]:
        return list(getattr(self.inner, "tool_names", []))

    def get(self, name: str) -> Any:
        return self.inner.get(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        return self.inner.get_definitions()

    def register(self, tool: Any) -> None:
        """Register a tool while keeping governance metadata in sync."""
        self.inner.register(tool)
        self.manifest_cache.register_tool(tool)

    def set_trace_writer(self, trace_writer: Any | None) -> None:
        self.decision_recorder.set_trace_writer(trace_writer)

    def execute(self, name: str, params: dict[str, Any]) -> str:
        """Evaluate policy, then delegate to the wrapped ToolRegistry if allowed."""

        if self.context.mode == "off":
            return self.inner.execute(name, params)

        manifest = self.manifest_cache.get(name)
        try:
            decision = self.policy.evaluate(name=name, params=params, manifest=manifest, context=self.context)
        except Exception as exc:  # noqa: BLE001 - wrapper must also fail safe
            audit = build_param_audit(params)
            action = "deny" if _must_deny_on_policy_exception(manifest, self.context.surface) else "warn"
            decision = PolicyDecision(
                tool_name=name,
                action=action,
                mode=self.context.mode,
                reasons=[f"Policy evaluation failed fail-safe: {exc.__class__.__name__}"],
                rule_id="policy_exception",
                params_hash=audit.params_hash,
                params_preview=audit.preview,
            )
        self.decision_recorder.record(decision, manifest=manifest)

        if decision.action == "deny":
            if self.context.mode == "enforce":
                self.decision_recorder.record_denied(decision, trace_status="denied", shadow=False)
                raise PolicyDenied(decision, shadow=False)
            if manifest.risk_level in HIGH_RISK_DENY:
                self.decision_recorder.record_denied(decision, trace_status="skipped", shadow=True)
                raise PolicyDenied(decision, shadow=True)
            # Low/medium risk observe/warn records the deny as a warning and continues.

        return self.inner.execute(name, params)

    def __contains__(self, name: str) -> bool:
        return name in getattr(self.inner, "tool_names", [])

    def __len__(self) -> int:
        return len(getattr(self.inner, "tool_names", []))


def govern_registry(
    registry: Any,
    *,
    surface: ToolSurface,
    mode: str | None = None,
    context: RuntimeContext | None = None,
    decision_recorder: DecisionRecorder | None = None,
) -> GovernedToolRegistry:
    """Wrap an existing registry with the governance runtime."""

    runtime_context = context or RuntimeContext(surface=surface, mode=mode or get_governance_mode())
    return GovernedToolRegistry(
        registry,
        manifest_cache=ManifestCache.from_registry(registry, surface=surface),
        context=runtime_context,
        decision_recorder=decision_recorder,
    )


def _must_deny_on_policy_exception(manifest: Any, surface: ToolSurface) -> bool:
    risk = getattr(manifest, "risk_level", None)
    return risk in HIGH_RISK_DENY or surface in {
        ToolSurface.REMOTE_API,
        ToolSurface.MCP_SSE,
        ToolSurface.MCP_HTTP,
        ToolSurface.SWARM,
        ToolSurface.SCHEDULER,
        ToolSurface.LIVE_CONNECTOR,
        ToolSurface.CHANNEL_BOT,
    }
