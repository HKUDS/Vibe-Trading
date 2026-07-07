"""Governed tool registry wrapper with a deny barrier before execution."""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel

from src.agent.tools import BaseTool, ToolRegistry
from src.governance.config import get_governance_mode
from src.governance.decision_recorder import DecisionRecorder
from src.governance.decisions import GovernanceMode, PolicyDecision, RecordedPolicyDecision, RuntimeContext, build_param_audit
from src.governance.discovery import ManifestCache, discover_tool_manifest
from src.governance.errors import PolicyDenied
from src.governance.manifest import RiskLevel, ToolManifest, ToolSurface
from src.governance.policy_engine import PolicyEngine

HIGH_RISK_DENY_LEVELS = {"R4_TRADE_WRITE", "R5_SHELL"}


class GovernanceState(BaseModel):
    """Authoritative high-risk execution state returned by a provider."""

    state_authoritative: bool = False
    live_authorized: bool = False
    user_authenticated: bool = False
    budget_available: bool = False


class GovernanceStateProvider:
    """Provider interface for authoritative high-risk runtime state."""

    def get_state(self, *, context: RuntimeContext, tool_name: str, params: dict[str, Any]) -> GovernanceState:
        """Return authoritative state for a high-risk execution attempt."""
        del context, tool_name, params
        return GovernanceState()


class GovernedToolRegistry:
    """Wrap a ToolRegistry with policy evaluation and explicit deny barrier."""

    def __init__(
        self,
        inner: ToolRegistry,
        *,
        manifest_cache: ManifestCache | None = None,
        policy: Any | None = None,
        decision_recorder: Any | None = None,
        context: RuntimeContext | None = None,
    ) -> None:
        self._inner = inner
        self.manifest_cache = manifest_cache
        surface = manifest_cache.surface if manifest_cache is not None else ToolSurface.LOCAL_API
        self.policy = policy if policy is not None else PolicyEngine()
        self.context = context if context is not None else RuntimeContext(surface=surface, mode=get_governance_mode())
        self.decision_recorder = decision_recorder if decision_recorder is not None else DecisionRecorder()
        self._fallback_recorder = (
            self.decision_recorder
            if _has_hardened_recorder_api(self.decision_recorder)
            else DecisionRecorder(artifact_store=None)
        )

    def execute(self, name: str, params: dict[str, Any]) -> str:
        """Execute a tool through governance while preserving ToolRegistry API."""
        mode = _effective_mode(self.context.mode)
        tool = self._inner.get(name)
        if tool is None:
            return self._inner.execute(name, params)

        manifest = self._manifest_for_tool(name, tool)
        risk_level = _risk_value(manifest.risk_level)
        if mode == "off":
            return self._inner.execute(name, params)

        raw_decision = self._evaluate_policy(name=name, params=params, manifest=manifest)
        raw_decision = _normalize_decision(raw_decision, manifest=manifest, context=self.context)
        state_decision = _state_gate_decision(
            name=name,
            params=params,
            manifest=manifest,
            context=self.context,
            policy_engine_version=getattr(raw_decision, "policy_engine_version", "state-gate-v1.2.1"),
            tool=tool,
        )
        if raw_decision.action != "deny" and state_decision is not None:
            raw_decision = _normalize_decision(state_decision, manifest=manifest, context=self.context)

        envelope = self._prepare_envelope(raw_decision, params=params)

        if raw_decision.action == "deny" and risk_level in HIGH_RISK_DENY_LEVELS:
            envelope.deny_barrier_engaged = True
            envelope.shadow_deny = True
            envelope.status = "shadow_denied"
            envelope.inner_tool_executed = False
            self._record_denial(envelope, raw_decision, shadow=True)
            raise PolicyDenied(envelope, shadow=True, trace_status="skipped")

        if raw_decision.action == "deny" and mode == "enforce":
            envelope.inner_tool_executed = False
            self._record_denial(envelope, raw_decision, shadow=False)
            raise PolicyDenied(envelope, shadow=False, trace_status="denied")

        self._record_pre_execution(envelope, raw_decision, manifest)
        try:
            result = self._inner.execute(name, params)
            envelope.inner_tool_executed = True
            self._record_post_execution(envelope, status="completed")
            return result
        except Exception as exc:
            envelope.inner_tool_executed = True
            self._record_post_execution(envelope, status="failed", error=exc)
            raise

    def get(self, name: str) -> Any | None:
        """Return a metadata proxy whose execute path re-enters governance."""
        tool = self._inner.get(name)
        if tool is None:
            return None
        return GovernedToolProxy(self, tool)

    def register(self, tool: BaseTool) -> None:
        """Register a tool while keeping manifest cache synchronized."""
        register = getattr(self._inner, "register", None)
        if not callable(register):
            raise AttributeError("wrapped registry does not support register")
        register(tool)
        if self.manifest_cache is not None:
            self.manifest_cache.register(tool)

    def get_definitions(self) -> list[dict[str, Any]]:
        return self._inner.get_definitions()

    def set_trace_writer(self, trace_writer: Any | None) -> None:
        """Attach a trace writer to compatible recorder implementations."""
        if hasattr(self.decision_recorder, "set_trace_writer"):
            self.decision_recorder.set_trace_writer(trace_writer)
        if hasattr(self._fallback_recorder, "trace_writer"):
            self._fallback_recorder.trace_writer = trace_writer

    @property
    def tool_names(self) -> list[str]:
        return list(getattr(self._inner, "tool_names", []))

    def __len__(self) -> int:
        return len(getattr(self._inner, "tool_names", []))

    def __contains__(self, name: str) -> bool:
        return name in getattr(self._inner, "tool_names", [])

    def _manifest_for_tool(self, name: str, tool: Any) -> ToolManifest:
        if self.manifest_cache is not None:
            return self.manifest_cache.get(name)
        return manifest_for_tool(tool, surface=_surface_enum(getattr(self.context, "surface", ToolSurface.LOCAL_API)))

    def _evaluate_policy(self, *, name: str, params: dict[str, Any], manifest: ToolManifest) -> PolicyDecision:
        try:
            return self.policy.evaluate(name=name, params=params, manifest=manifest, context=self.context)
        except Exception as exc:  # noqa: BLE001 - wrapper must fail safe.
            audit = build_param_audit(params)
            action = "deny" if _must_deny_on_policy_exception(manifest, self.context.surface) else "warn"
            return PolicyDecision(
                tool_name=name,
                action=action,
                mode=self.context.mode,
                risk_level=_risk_value(manifest.risk_level),
                reasons=[f"Policy evaluation failed fail-safe: {exc.__class__.__name__}"],
                reason_codes=["POLICY_EXCEPTION_FAIL_SAFE"],
                rule_id="policy_exception",
                params_hash=audit.params_hash,
                params_preview=audit.preview,
            )

    def _prepare_envelope(self, decision: PolicyDecision, *, params: dict[str, Any]) -> RecordedPolicyDecision:
        return self._fallback_recorder.prepare(decision, params=params, context=self.context)

    def _record_denial(self, envelope: RecordedPolicyDecision, decision: PolicyDecision, *, shadow: bool) -> None:
        _record_compat_decision(self.decision_recorder, decision, envelope=envelope, manifest=None)
        _record_denial_best_effort(self._fallback_recorder, envelope)
        if hasattr(self.decision_recorder, "record_denied") and not _has_hardened_recorder_api(self.decision_recorder):
            try:
                self.decision_recorder.record_denied(
                    decision,
                    trace_status="skipped" if shadow else "denied",
                    shadow=shadow,
                )
            except Exception as exc:  # noqa: BLE001 - denial must remain denial.
                envelope.metadata["compat_denial_recording_error"] = str(exc)

    def _record_pre_execution(
        self,
        envelope: RecordedPolicyDecision,
        decision: PolicyDecision,
        manifest: ToolManifest,
    ) -> None:
        _record_compat_decision(self.decision_recorder, decision, envelope=envelope, manifest=manifest)
        if _has_hardened_recorder_api(self._fallback_recorder):
            try:
                self._fallback_recorder.record_pre_execution_best_effort(envelope)
            except Exception as exc:  # noqa: BLE001 - best-effort evidence must not control low-risk execution.
                envelope.metadata["pre_execution_recording_error"] = str(exc)

    def _record_post_execution(
        self,
        envelope: RecordedPolicyDecision,
        *,
        status: str,
        error: BaseException | None = None,
    ) -> None:
        if _has_hardened_recorder_api(self._fallback_recorder):
            try:
                self._fallback_recorder.record_post_execution_best_effort(envelope, status=status, error=error)
            except Exception as exc:  # noqa: BLE001 - post evidence is best effort.
                envelope.metadata["post_execution_recording_error"] = str(exc)


class GovernedToolProxy(BaseTool):
    """Metadata-only public tool view whose execute path re-enters governance."""

    __slots__ = ("_governed_registry",)

    def __init__(self, registry: GovernedToolRegistry, tool: BaseTool) -> None:
        self._governed_registry = registry
        self.name = tool.name
        self.description = tool.description
        self.parameters = dict(tool.parameters or {})
        self.repeatable = bool(getattr(tool, "repeatable", False))
        self.is_readonly = bool(getattr(tool, "is_readonly", True))
        if hasattr(tool, "risk_level"):
            self.risk_level = getattr(tool, "risk_level")
        spec = getattr(tool, "_spec", None)
        if spec is not None:
            self.mcp_server_name = getattr(spec, "server_name", None)
            self.mcp_remote_tool_name = getattr(spec, "remote_name", None)

    def execute(self, **kwargs: Any) -> str:
        """Execute via GovernedToolRegistry.execute(), never the raw tool."""
        return self._governed_registry.execute(self.name, dict(kwargs))


def govern_registry(
    registry: Any,
    *,
    surface: ToolSurface | str,
    mode: str | None = None,
    context: RuntimeContext | None = None,
    decision_recorder: Any | None = None,
) -> GovernedToolRegistry:
    """Wrap an existing registry with the governance runtime."""
    if isinstance(registry, GovernedToolRegistry):
        return registry
    surface_enum = _surface_enum(surface)
    runtime_context = context or RuntimeContext(surface=surface_enum, mode=mode or get_governance_mode())
    return GovernedToolRegistry(
        registry,
        manifest_cache=ManifestCache.from_registry(registry, surface=surface_enum),
        context=runtime_context,
        decision_recorder=decision_recorder,
    )


def manifest_for_tool(tool: Any, *, surface: ToolSurface | str = ToolSurface.LOCAL_API) -> ToolManifest:
    """Build a conservative manifest from existing BaseTool metadata."""
    manifest = discover_tool_manifest(tool, surface=_surface_enum(surface))
    explicit_risk = getattr(tool, "risk_level", None)
    if explicit_risk:
        manifest = manifest.model_copy(update={"risk_level": _risk_enum(explicit_risk)})
    return manifest


def _record_denial_best_effort(recorder: Any, envelope: RecordedPolicyDecision) -> None:
    """Record a denial while preserving fail-closed PolicyDenied semantics."""
    if not hasattr(recorder, "record_best_effort"):
        return
    try:
        recorder.record_best_effort(envelope)
    except Exception as exc:  # noqa: BLE001 - denial must remain denial if recorder fails.
        envelope.metadata["evidence_recording_error"] = str(exc)
        envelope.write_outcome = None


def _record_compat_decision(
    recorder: Any,
    decision: PolicyDecision,
    *,
    envelope: RecordedPolicyDecision,
    manifest: ToolManifest | None,
) -> None:
    if not hasattr(recorder, "record") or _has_hardened_recorder_api(recorder):
        return
    try:
        recorder.record(decision, manifest=manifest)
    except Exception as exc:  # noqa: BLE001 - high-risk denial remains fail-closed.
        envelope.metadata["compat_decision_recording_error"] = str(exc)


def _state_gate_decision(
    *,
    name: str,
    params: dict[str, Any],
    manifest: ToolManifest,
    context: RuntimeContext,
    policy_engine_version: str,
    tool: Any | None = None,
) -> PolicyDecision | None:
    """Deny high-risk live/write execution unless authoritative state allows it."""
    if _risk_value(manifest.risk_level) != "R4_TRADE_WRITE":
        return None

    if _legacy_guard_wrapper_can_execute(context=context, tool=tool):
        return None

    provider = context.state_provider
    if provider is None:
        return _state_deny_decision(
            name=name,
            risk_level=_risk_value(manifest.risk_level),
            reason="authoritative governance state provider is required",
            reason_code="P40_STATE_PROVIDER_REQUIRED",
            policy_engine_version=policy_engine_version,
        )
    try:
        raw_state = provider.get_state(context=context, tool_name=name, params=dict(params))
    except Exception as exc:  # noqa: BLE001 - state provider failure is a fail-closed denial.
        return _state_deny_decision(
            name=name,
            risk_level=_risk_value(manifest.risk_level),
            reason=f"authoritative governance state provider failed: {exc}",
            reason_code="P40_STATE_PROVIDER_FAILED",
            policy_engine_version=policy_engine_version,
        )

    state = raw_state if isinstance(raw_state, GovernanceState) else GovernanceState.model_validate(raw_state)
    if not state.state_authoritative:
        return _state_deny_decision(
            name=name,
            risk_level=_risk_value(manifest.risk_level),
            reason="governance state is not authoritative",
            reason_code="P40_STATE_NOT_AUTHORITATIVE",
            policy_engine_version=policy_engine_version,
        )
    if not state.live_authorized:
        return _state_deny_decision(
            name=name,
            risk_level=_risk_value(manifest.risk_level),
            reason="live authorization is missing",
            reason_code="P40_LIVE_AUTH_REQUIRED",
            policy_engine_version=policy_engine_version,
        )
    if not state.user_authenticated:
        return _state_deny_decision(
            name=name,
            risk_level=_risk_value(manifest.risk_level),
            reason="user authentication is missing",
            reason_code="P40_USER_AUTH_REQUIRED",
            policy_engine_version=policy_engine_version,
        )
    if not state.budget_available:
        return _state_deny_decision(
            name=name,
            risk_level=_risk_value(manifest.risk_level),
            reason="budget is not available for high-risk execution",
            reason_code="P40_BUDGET_REQUIRED",
            policy_engine_version=policy_engine_version,
        )
    return None


def _legacy_guard_wrapper_can_execute(*, context: RuntimeContext, tool: Any | None) -> bool:
    """Permit old route tests to reach the live guard wrapper, not raw broker writes."""
    if context.state_provider is not None:
        return False
    if _surface_enum(context.surface) != ToolSurface.LIVE_CONNECTOR:
        return False
    live_state = context.live_state if isinstance(context.live_state, dict) else {}
    required = {
        "mandate_active",
        "kill_switch_clear",
        "explicit_user_consent",
        "live_order_guard",
        "connector_profile_selected",
    }
    if not all(live_state.get(check) is True for check in required):
        return False
    if tool is None:
        return False
    tool_name = str(getattr(tool, "name", "")).lower()
    description = str(getattr(tool, "description", "")).lower()
    class_name = tool.__class__.__name__.lower()
    return "liveorderguardtool" in class_name or "live guard" in f"{tool_name} {description}"


def _state_deny_decision(
    *,
    name: str,
    risk_level: str,
    reason: str,
    reason_code: str,
    policy_engine_version: str,
) -> PolicyDecision:
    return PolicyDecision(
        tool_name=name,
        action="deny",
        risk_level=risk_level,
        reasons=[reason],
        reason_codes=[reason_code],
        required_checks=["authoritative_governance_state"],
        check_results={"authoritative_governance_state": False},
        policy_engine_version=policy_engine_version,
    )


def _normalize_decision(
    decision: PolicyDecision,
    *,
    manifest: ToolManifest,
    context: RuntimeContext,
) -> PolicyDecision:
    risk_level = _risk_value(manifest.risk_level)
    update: dict[str, Any] = {"risk_level": risk_level, "mode": context.mode}
    if not decision.reason_codes and decision.rule_id:
        update["reason_codes"] = [decision.rule_id]
    return decision.model_copy(update=update)


def _must_deny_on_policy_exception(manifest: Any, surface: ToolSurface | str) -> bool:
    return _risk_value(getattr(manifest, "risk_level", None)) in HIGH_RISK_DENY_LEVELS or _surface_enum(surface) in {
        ToolSurface.REMOTE_API,
        ToolSurface.MCP_SSE,
        ToolSurface.MCP_HTTP,
        ToolSurface.SWARM,
        ToolSurface.SCHEDULER,
        ToolSurface.LIVE_CONNECTOR,
        ToolSurface.CHANNEL_BOT,
    }


def _risk_value(value: Any) -> str:
    if isinstance(value, RiskLevel):
        return value.value
    return str(value or "UNCLASSIFIED")


def _risk_enum(value: Any) -> RiskLevel:
    raw = _risk_value(value)
    aliases = {
        "R1_READ": RiskLevel.R0_READ,
        "R2_WRITE": RiskLevel.R1_WRITE_LOCAL,
    }
    if raw in aliases:
        return aliases[raw]
    try:
        return RiskLevel(raw)
    except ValueError:
        return RiskLevel.UNCLASSIFIED


def _surface_enum(value: ToolSurface | str | Any) -> ToolSurface:
    if isinstance(value, ToolSurface):
        return value
    try:
        return ToolSurface(str(value))
    except ValueError:
        return ToolSurface.LOCAL_API


def _has_hardened_recorder_api(recorder: Any) -> bool:
    return hasattr(recorder, "prepare") and hasattr(recorder, "record_best_effort")


def _effective_mode(context_mode: GovernanceMode) -> Literal["off", "observe", "warn", "enforce"]:
    raw = os.getenv("VIBE_TRADING_GOVERNANCE_MODE")
    if raw is None:
        return context_mode
    value = raw.strip().lower()
    if value in {"off", "observe", "warn", "enforce"}:
        return value  # type: ignore[return-value]
    return context_mode
