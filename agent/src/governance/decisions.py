"""Runtime context and policy decision models."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.governance.evidence_identity import EvidenceIdentity, EvidenceWriteOutcome, SCHEMA_VERSION
from src.governance.manifest import ToolSurface
from src.reliability.redaction import redact_secrets

GovernanceMode = Literal["off", "observe", "warn", "enforce"]
PolicyAction = Literal["allow", "warn", "deny"]
RecordedDecisionStatus = Literal["allowed", "warned", "denied", "shadow_denied", "failed", "skipped"]


def utc_now() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class RuntimeContext(BaseModel):
    """Context available to governance at call time."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    surface: ToolSurface | str = ToolSurface.LOCAL_API
    mode: GovernanceMode = "observe"
    session_id: str | None = None
    run_id: str | None = None
    trial_id: str | None = None
    protocol_hash: str | None = None
    user_auth_state: dict[str, Any] = Field(default_factory=dict)
    live_state: dict[str, Any] = Field(default_factory=dict)
    budget_state: dict[str, Any] = Field(default_factory=dict)
    state_provider: Any | None = None


class ParamAudit(BaseModel):
    """Hash plus redacted preview for tool parameters."""

    params_hash: str
    preview: dict[str, Any]


class PolicyDecision(BaseModel):
    """Pure policy-engine output. This model does not write or execute."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = SCHEMA_VERSION
    decision_id: str = Field(default_factory=lambda: f"pd_{uuid4().hex}")
    tool_name: str
    action: PolicyAction
    mode: GovernanceMode = "observe"
    risk_level: str = "R1_READ"
    reasons: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)
    check_results: dict[str, bool | str | None] = Field(default_factory=dict)
    rule_id: str | None = None
    params_hash: str | None = None
    params_preview: dict[str, Any] | None = None
    policy_engine_version: str = "vibe-governance-v1.2.1"
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at")
    @classmethod
    def _created_at_must_be_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class RecordedPolicyDecision(BaseModel):
    """Policy decision envelope persisted to trace/artifact evidence."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = SCHEMA_VERSION
    decision_id: str
    tool_name: str
    action: PolicyAction
    status: RecordedDecisionStatus
    mode: GovernanceMode
    surface: str
    risk_level: str
    reasons: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)
    check_results: dict[str, bool | str | None] = Field(default_factory=dict)
    rule_id: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    trial_id: str | None = None
    protocol_hash: str | None = None
    shadow_deny: bool = False
    deny_barrier_engaged: bool = False
    inner_tool_executed: bool | None = None
    params_hash: str | None = None
    redacted_params_preview: dict[str, Any] = Field(default_factory=dict)
    evidence_identity: EvidenceIdentity
    write_outcome: EvidenceWriteOutcome | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    parent_artifacts: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at")
    @classmethod
    def _created_at_must_be_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)


def build_param_audit(params: dict[str, Any] | None) -> ParamAudit:
    """Build a stable hash and redacted preview without storing raw params."""

    redacted = redact_secrets(params or {})
    preview = _json_safe(redacted)
    if not isinstance(preview, dict):
        preview = {"value": preview}
    payload = json.dumps(preview, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return ParamAudit(params_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(), preview=preview)


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return repr(value)[:120]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item, depth=depth + 1) for key, item in list(value.items())[:50]}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item, depth=depth + 1) for item in list(value)[:50]]
    return repr(value)[:200]
