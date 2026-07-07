"""Policy decision models for the governed tool runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.governance.evidence_identity import EvidenceIdentity, EvidenceWriteOutcome, SCHEMA_VERSION

PolicyAction = Literal["allow", "warn", "deny"]
RecordedDecisionStatus = Literal["allowed", "warned", "denied", "shadow_denied", "failed", "skipped"]
GovernanceMode = Literal["off", "observe", "warn", "enforce"]


def utc_now() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class PolicyDecision(BaseModel):
    """Pure policy-engine output. This model does not write or execute."""

    schema_version: str = SCHEMA_VERSION
    tool_name: str
    action: PolicyAction
    risk_level: str
    reasons: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)
    check_results: dict[str, bool | str | None] = Field(default_factory=dict)
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

