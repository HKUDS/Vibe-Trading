"""Runtime wrapper around the existing ToolRegistry."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Protocol

from src.governance.budget import BudgetExceeded, BudgetManager
from src.governance.config import get_governance_mode
from src.governance.decisions import PolicyDecision, RuntimeContext, build_param_audit
from src.governance.discovery import ManifestCache
from src.governance.errors import PolicyDenied
from src.governance.manifest import RiskLevel, ToolSurface
from src.governance.policy_engine import PolicyEngine
from src.governance.trace_adapter import DecisionRecorder


HIGH_RISK_DENY = {RiskLevel.R4_TRADE_WRITE, RiskLevel.R5_SHELL}


class GovernanceStateProvider(Protocol):
    """Authoritative runtime state source for policy checks."""

    def get_live_state(self, context: RuntimeContext) -> Mapping[str, Any]:
        ...

    def get_user_auth_state(self, context: RuntimeContext) -> Mapping[str, Any]:
        ...

    def get_budget_state(self, context: RuntimeContext) -> Mapping[str, Any]:
        ...


class NullGovernanceStateProvider:
    """Fail-closed provider used when no authoritative state source is wired."""

    def get_live_state(self, context: RuntimeContext) -> Mapping[str, Any]:
        del context
        return {}

    def get_user_auth_state(self, context: RuntimeContext) -> Mapping[str, Any]:
        del context
        return {}

    def get_budget_state(self, context: RuntimeContext) -> Mapping[str, Any]:
        del context
        return {}


class GovernedToolProxy:
    """Metadata proxy that routes execution back through governance."""

    __slots__ = ("_registry", "_name", "__raw_tool")

    def __init__(self, registry: "GovernedToolRegistry", name: str, raw_tool: Any) -> None:
        self._registry = registry
        self._name = name
        self.__raw_tool = raw_tool

    def execute(self, **params: Any) -> str:
        return self._registry.execute(self._name, params)

    @property
    def __class__(self) -> type:
        return self.__raw_tool.__class__

    def __getattr__(self, attr: str) -> Any:
        if attr == "execute" or (attr.startswith("_") and attr != "_spec"):
            raise AttributeError(attr)
        return getattr(self.__raw_tool, attr)


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
        state_provider: GovernanceStateProvider | None = None,
        budget_manager: BudgetManager | None = None,
    ) -> None:
        self._inner = inner
        self.manifest_cache = manifest_cache
        self.policy = policy or PolicyEngine()
        self.context = context or RuntimeContext(surface=manifest_cache.surface, mode=get_governance_mode())
        self.decision_recorder = decision_recorder or DecisionRecorder()
        self._state_provider = state_provider or NullGovernanceStateProvider()
        self._budget_manager = budget_manager

    @property
    def tool_names(self) -> list[str]:
        return list(getattr(self._inner, "tool_names", []))

    def get(self, name: str) -> Any:
        raw_tool = self._inner.get(name)
        if raw_tool is None:
            return None
        return GovernedToolProxy(self, name, raw_tool)

    def register(self, tool: Any) -> None:
        """Delegate dynamic tool registration while keeping manifests in sync."""

        register = getattr(self._inner, "register", None)
        if not callable(register):
            raise AttributeError("wrapped registry does not support register")
        register(tool)
        self.manifest_cache.register(tool)

    def get_definitions(self) -> list[dict[str, Any]]:
        return self._inner.get_definitions()

    def set_trace_writer(self, trace_writer: Any | None) -> None:
        self.decision_recorder.set_trace_writer(trace_writer)

    def execute(self, name: str, params: dict[str, Any]) -> str:
        """Evaluate policy, then delegate to the wrapped ToolRegistry if allowed."""

        manifest = self.manifest_cache.get(name)
        execution_params = _copy_params(params)
        if self.context.mode == "off":
            if manifest.risk_level in HIGH_RISK_DENY:
                audit = build_param_audit(execution_params)
                decision = PolicyDecision(
                    tool_name=name,
                    action="deny",
                    mode=self.context.mode,
                    reasons=["High-risk tools cannot bypass governance in off mode"],
                    rule_id="governance_off_high_risk",
                    params_hash=audit.params_hash,
                    params_preview=audit.preview,
                )
                try:
                    self.decision_recorder.record(decision, manifest=manifest)
                    self.decision_recorder.record_denied(decision, trace_status="skipped", shadow=True)
                except Exception:
                    pass
                raise PolicyDenied(decision, shadow=True)
            return self._inner.execute(name, execution_params)

        effective_context = self._build_effective_context()
        policy_params = _copy_params(execution_params)
        try:
            decision = self.policy.evaluate(name=name, params=policy_params, manifest=manifest, context=effective_context)
        except Exception as exc:  # noqa: BLE001 - wrapper must also fail safe
            audit = build_param_audit(execution_params)
            action = "deny" if _must_deny_on_policy_exception(manifest, effective_context.surface) else "warn"
            decision = PolicyDecision(
                tool_name=name,
                action=action,
                mode=effective_context.mode,
                reasons=[f"Policy evaluation failed fail-safe: {exc.__class__.__name__}"],
                rule_id="policy_exception",
                params_hash=audit.params_hash,
                params_preview=audit.preview,
            )
        try:
            self.decision_recorder.record(decision, manifest=manifest)
        except Exception as exc:  # noqa: BLE001 - audit failure must not open high-risk paths
            if _must_fail_closed_on_recording_exception(manifest, effective_context):
                audit = build_param_audit(execution_params)
                denied = PolicyDecision(
                    tool_name=name,
                    action="deny",
                    mode=effective_context.mode,
                    reasons=[f"Policy decision recording failed fail-safe: {exc.__class__.__name__}"],
                    rule_id="trace_record_failed",
                    params_hash=audit.params_hash,
                    params_preview=audit.preview,
                )
                raise PolicyDenied(denied, shadow=manifest.risk_level in HIGH_RISK_DENY) from exc
            raise

        if decision.action == "deny":
            if effective_context.mode == "enforce":
                self.decision_recorder.record_denied(decision, trace_status="denied", shadow=False)
                raise PolicyDenied(decision, shadow=False)
            if manifest.risk_level in HIGH_RISK_DENY:
                self.decision_recorder.record_denied(decision, trace_status="skipped", shadow=True)
                raise PolicyDenied(decision, shadow=True)
            # Low/medium risk observe/warn records the deny as a warning and continues.

        if effective_context.mode == "warn" and decision.action in {"deny", "warn"}:
            self.decision_recorder.record_warning(decision)

        if self._budget_manager is not None:
            try:
                self._budget_manager.record_tool_call(risk_level=manifest.risk_level)
            except BudgetExceeded as exc:
                audit = build_param_audit(execution_params)
                decision = PolicyDecision(
                    tool_name=name,
                    action="deny",
                    mode=effective_context.mode,
                    reasons=[f"Governance budget exceeded: {exc}"],
                    rule_id="budget_exceeded",
                    params_hash=audit.params_hash,
                    params_preview=audit.preview,
                )
                self.decision_recorder.record(decision, manifest=manifest)
                self.decision_recorder.record_denied(decision, trace_status="denied", shadow=False)
                raise PolicyDenied(decision, shadow=False) from exc

        return self._inner.execute(name, execution_params)

    def __contains__(self, name: str) -> bool:
        return name in getattr(self._inner, "tool_names", [])

    def __len__(self) -> int:
        return len(getattr(self._inner, "tool_names", []))

    def _build_effective_context(self) -> RuntimeContext:
        return self.context.with_authoritative_state(
            live_state=self._state_provider.get_live_state(self.context),
            user_auth_state=self._state_provider.get_user_auth_state(self.context),
            budget_state=self._state_provider.get_budget_state(self.context),
        )


def govern_registry(
    registry: Any,
    *,
    surface: ToolSurface,
    mode: str | None = None,
    context: RuntimeContext | None = None,
    decision_recorder: DecisionRecorder | None = None,
    state_provider: GovernanceStateProvider | None = None,
    budget_manager: BudgetManager | None = None,
) -> GovernedToolRegistry:
    """Wrap an existing registry with the governance runtime."""

    runtime_context = context or RuntimeContext(surface=surface, mode=mode or get_governance_mode())
    return GovernedToolRegistry(
        registry,
        manifest_cache=ManifestCache.from_registry(registry, surface=surface),
        context=runtime_context,
        decision_recorder=decision_recorder,
        state_provider=state_provider,
        budget_manager=budget_manager,
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


def _must_fail_closed_on_recording_exception(manifest: Any, context: RuntimeContext) -> bool:
    return _must_deny_on_policy_exception(manifest, context.surface)


def _copy_params(params: dict[str, Any]) -> dict[str, Any]:
    try:
        copied = deepcopy(params)
    except Exception:  # noqa: BLE001 - exotic objects still get a mapping boundary
        copied = dict(params)
    return copied
