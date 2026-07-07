"""Governed tool registry wrapper with a deny barrier before execution."""

from __future__ import annotations

import json
import os
from typing import Any, Literal

from pydantic import BaseModel

from src.agent.tools import ToolRegistry
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
        self.inner = inner
        self.policy = policy if policy is not None else DefaultPolicyEngine()
        self.decision_recorder = decision_recorder if decision_recorder is not None else DecisionRecorder()
        self.context = context if context is not None else RuntimeContext()

    def execute(self, name: str, params: dict[str, Any]) -> str:
        """Execute a tool through governance while preserving ToolRegistry API."""
        if _effective_mode(self.context.mode) == "off":
            return self.inner.execute(name, params)

        tool = self.inner.get(name)
        if tool is None:
            return self.inner.execute(name, params)

        manifest = manifest_for_tool(tool)
        raw_decision = self.policy.evaluate(name=name, params=params, manifest=manifest, context=self.context)
        envelope = self.decision_recorder.prepare(raw_decision, params=params, context=self.context)

        if raw_decision.action == "deny" and manifest.risk_level in HIGH_RISK_DENY_LEVELS:
            envelope.deny_barrier_engaged = True
            envelope.shadow_deny = True
            envelope.status = "shadow_denied"
            envelope.inner_tool_executed = False
            self.decision_recorder.record_best_effort(envelope)
            raise PolicyDenied(envelope)

        if raw_decision.action == "deny" and self.context.mode == "enforce":
            envelope.inner_tool_executed = False
            self.decision_recorder.record_best_effort(envelope)
            raise PolicyDenied(envelope)

        self.decision_recorder.record_pre_execution_best_effort(envelope)
        try:
            result = self.inner.execute(name, params)
            envelope.inner_tool_executed = True
            self.decision_recorder.record_post_execution_best_effort(envelope, status="completed")
            return result
        except Exception as exc:
            envelope.inner_tool_executed = True
            self.decision_recorder.record_post_execution_best_effort(envelope, status="failed", error=exc)
            raise

    def get(self, name: str) -> Any | None:
        return self.inner.get(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        return self.inner.get_definitions()

    @property
    def tool_names(self) -> list[str]:
        return self.inner.tool_names

    def __len__(self) -> int:
        return len(self.inner)

    def __contains__(self, name: str) -> bool:
        return name in self.inner


def manifest_for_tool(tool: Any) -> ToolManifest:
    """Build a conservative manifest from existing BaseTool metadata."""
    name = getattr(tool, "name", "")
    explicit_risk = getattr(tool, "risk_level", None)
    risk_level = explicit_risk or _infer_risk_level(name=name, is_readonly=getattr(tool, "is_readonly", True))
    return ToolManifest(name=name, risk_level=risk_level, is_readonly=bool(getattr(tool, "is_readonly", True)))


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

