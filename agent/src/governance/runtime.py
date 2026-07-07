"""Governed tool registry wrapper with a deny barrier before execution."""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.agent.tools import BaseTool, ToolRegistry
from src.governance.decision_recorder import DecisionRecorder
from src.governance.decisions import GovernanceMode, PolicyDecision, RecordedPolicyDecision

HIGH_RISK_DENY_LEVELS = {"R4_TRADE_WRITE", "R5_SHELL"}


class RuntimeContext(BaseModel):
    """Governance context supplied by a runtime surface."""

    mode: GovernanceMode = "observe"
    surface: str = "unknown"
    run_id: str | None = None
    session_id: str | None = None
    trial_id: str | None = None
    protocol_hash: str | None = None
    live_state: dict[str, Any] = Field(default_factory=dict)
    user_auth_state: dict[str, Any] = Field(default_factory=dict)
    budget_state: dict[str, Any] = Field(default_factory=dict)
    state_provider: Any | None = None


class ToolManifest(BaseModel):
    """Minimal tool manifest used by the pure policy engine."""

    name: str
    risk_level: str = "R1_READ"
    is_readonly: bool = True


class PolicyDenied(RuntimeError):
    """Raised when policy denies a tool call before inner execution."""

    def __init__(self, envelope: RecordedPolicyDecision) -> None:
        super().__init__(f"policy denied tool {envelope.tool_name}: {', '.join(envelope.reasons)}")
        self.envelope = envelope


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


class DefaultPolicyEngine:
    """Small pure policy engine for v1.2.1 dangerous-tool defaults."""

    version = "default-governance-v1.2.1"

    def evaluate(
        self,
        *,
        name: str,
        params: dict[str, Any],
        manifest: ToolManifest,
        context: RuntimeContext,
    ) -> PolicyDecision:
        del params
        if manifest.risk_level in HIGH_RISK_DENY_LEVELS:
            return PolicyDecision(
                tool_name=name,
                action="deny",
                risk_level=manifest.risk_level,
                reasons=[f"{manifest.risk_level} tools require an explicit governed allow path"],
                reason_codes=[f"{manifest.risk_level}_DENIED"],
                policy_engine_version=self.version,
            )
        return PolicyDecision(
            tool_name=name,
            action="allow",
            risk_level=manifest.risk_level,
            reasons=[],
            policy_engine_version=self.version,
        )


class GovernedToolRegistry:
    """Wrap a ToolRegistry with policy evaluation and explicit deny barrier."""

    def __init__(
        self,
        inner: ToolRegistry,
        *,
        policy: Any | None = None,
        decision_recorder: DecisionRecorder | None = None,
        context: RuntimeContext | None = None,
    ) -> None:
        self._inner = inner
        self.policy = policy if policy is not None else DefaultPolicyEngine()
        self.decision_recorder = decision_recorder if decision_recorder is not None else DecisionRecorder()
        self.context = context if context is not None else RuntimeContext()

    def execute(self, name: str, params: dict[str, Any]) -> str:
        """Execute a tool through governance while preserving ToolRegistry API."""
        if _effective_mode(self.context.mode) == "off":
            return self._inner.execute(name, params)

        tool = self._inner.get(name)
        if tool is None:
            return self._inner.execute(name, params)

        manifest = manifest_for_tool(tool)
        raw_decision = self.policy.evaluate(name=name, params=params, manifest=manifest, context=self.context)
        state_decision = _state_gate_decision(
            name=name,
            params=params,
            manifest=manifest,
            context=self.context,
            policy_engine_version=getattr(raw_decision, "policy_engine_version", "state-gate-v1.2.1"),
        )
        if raw_decision.action != "deny" and state_decision is not None:
            raw_decision = state_decision
        envelope = self.decision_recorder.prepare(raw_decision, params=params, context=self.context)

        if raw_decision.action == "deny" and manifest.risk_level in HIGH_RISK_DENY_LEVELS:
            envelope.deny_barrier_engaged = True
            envelope.shadow_deny = True
            envelope.status = "shadow_denied"
            envelope.inner_tool_executed = False
            _record_denial_best_effort(self.decision_recorder, envelope)
            raise PolicyDenied(envelope)

        if raw_decision.action == "deny" and self.context.mode == "enforce":
            envelope.inner_tool_executed = False
            _record_denial_best_effort(self.decision_recorder, envelope)
            raise PolicyDenied(envelope)

        self.decision_recorder.record_pre_execution_best_effort(envelope)
        try:
            result = self._inner.execute(name, params)
            envelope.inner_tool_executed = True
            self.decision_recorder.record_post_execution_best_effort(envelope, status="completed")
            return result
        except Exception as exc:
            envelope.inner_tool_executed = True
            self.decision_recorder.record_post_execution_best_effort(envelope, status="failed", error=exc)
            raise

    def get(self, name: str) -> Any | None:
        tool = self._inner.get(name)
        if tool is None:
            return None
        return GovernedToolProxy(self, tool)

    def get_definitions(self) -> list[dict[str, Any]]:
        return self._inner.get_definitions()

    @property
    def tool_names(self) -> list[str]:
        return self._inner.tool_names

    def __len__(self) -> int:
        return len(self._inner)

    def __contains__(self, name: str) -> bool:
        return name in self._inner


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


def manifest_for_tool(tool: Any) -> ToolManifest:
    """Build a conservative manifest from existing BaseTool metadata."""
    name = getattr(tool, "name", "")
    explicit_risk = getattr(tool, "risk_level", None)
    risk_level = explicit_risk or _infer_risk_level(name=name, is_readonly=getattr(tool, "is_readonly", True))
    return ToolManifest(name=name, risk_level=risk_level, is_readonly=bool(getattr(tool, "is_readonly", True)))


def _record_denial_best_effort(recorder: DecisionRecorder, envelope: RecordedPolicyDecision) -> None:
    """Record a denial while preserving fail-closed PolicyDenied semantics."""
    try:
        recorder.record_best_effort(envelope)
    except Exception as exc:  # noqa: BLE001 - denial must remain denial if recorder fails.
        envelope.metadata["evidence_recording_error"] = str(exc)
        envelope.write_outcome = None


def _state_gate_decision(
    *,
    name: str,
    params: dict[str, Any],
    manifest: ToolManifest,
    context: RuntimeContext,
    policy_engine_version: str,
) -> PolicyDecision | None:
    """Deny high-risk live/write execution unless authoritative state allows it."""
    if manifest.risk_level != "R4_TRADE_WRITE":
        return None

    provider = context.state_provider
    if provider is None:
        return _state_deny_decision(
            name=name,
            risk_level=manifest.risk_level,
            reason="authoritative governance state provider is required",
            reason_code="P40_STATE_PROVIDER_REQUIRED",
            policy_engine_version=policy_engine_version,
        )
    try:
        raw_state = provider.get_state(context=context, tool_name=name, params=dict(params))
    except Exception as exc:  # noqa: BLE001 - state provider failure is a fail-closed denial.
        return _state_deny_decision(
            name=name,
            risk_level=manifest.risk_level,
            reason=f"authoritative governance state provider failed: {exc}",
            reason_code="P40_STATE_PROVIDER_FAILED",
            policy_engine_version=policy_engine_version,
        )

    state = raw_state if isinstance(raw_state, GovernanceState) else GovernanceState.model_validate(raw_state)
    if not state.state_authoritative:
        return _state_deny_decision(
            name=name,
            risk_level=manifest.risk_level,
            reason="governance state is not authoritative",
            reason_code="P40_STATE_NOT_AUTHORITATIVE",
            policy_engine_version=policy_engine_version,
        )
    if not state.live_authorized:
        return _state_deny_decision(
            name=name,
            risk_level=manifest.risk_level,
            reason="live authorization is missing",
            reason_code="P40_LIVE_AUTH_REQUIRED",
            policy_engine_version=policy_engine_version,
        )
    if not state.user_authenticated:
        return _state_deny_decision(
            name=name,
            risk_level=manifest.risk_level,
            reason="user authentication is missing",
            reason_code="P40_USER_AUTH_REQUIRED",
            policy_engine_version=policy_engine_version,
        )
    if not state.budget_available:
        return _state_deny_decision(
            name=name,
            risk_level=manifest.risk_level,
            reason="budget is not available for high-risk execution",
            reason_code="P40_BUDGET_REQUIRED",
            policy_engine_version=policy_engine_version,
        )
    return None


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


def _infer_risk_level(*, name: str, is_readonly: bool) -> str:
    lowered = name.lower()
    if lowered in {"bash", "background_run"} or "shell" in lowered:
        return "R5_SHELL"
    if any(fragment in lowered for fragment in ("place_order", "cancel_order", "trade_write", "order_write")):
        return "R4_TRADE_WRITE"
    if not is_readonly and any(fragment in lowered for fragment in ("trade", "order", "broker")):
        return "R4_TRADE_WRITE"
    return "R1_READ" if is_readonly else "R2_WRITE"


def _effective_mode(context_mode: GovernanceMode) -> Literal["off", "observe", "warn", "enforce"]:
    raw = os.getenv("VIBE_TRADING_GOVERNANCE_MODE")
    if raw is None:
        return context_mode
    value = raw.strip().lower()
    if value in {"off", "observe", "warn", "enforce"}:
        return value  # type: ignore[return-value]
    return context_mode

