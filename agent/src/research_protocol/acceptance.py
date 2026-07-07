"""Accepted-result gates for registered research experiments."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.research_protocol.registry import ProtocolRegistry


class AcceptanceError(ValueError):
    """Raised when a result cannot be accepted under IRR-AGL gates."""


class AcceptedResult(BaseModel):
    """Minimum evidence required before accepting a research result."""

    protocol_hash: str | None = None
    trial_count: int | None = None
    data_audit_ids: list[str] = Field(default_factory=list)
    policy_decision_ids: list[str] = Field(default_factory=list)
    backtest_artifact_refs: list[str] = Field(default_factory=list)
    alpha_artifact_refs: list[str] = Field(default_factory=list)
    best_trial: bool = False
    selection_policy: str | None = None
    abandoned_count: int = 0
    rejected_count: int = 0


def validate_accepted_result(result: AcceptedResult, *, registry: ProtocolRegistry | None = None) -> AcceptedResult:
    """Validate accepted-result gates and return the original result."""

    if not result.protocol_hash:
        raise AcceptanceError("accepted result requires a registered protocol_hash")
    if registry is not None and not registry.is_registered(result.protocol_hash):
        raise AcceptanceError("accepted result requires a registered protocol")
    if result.trial_count is None:
        raise AcceptanceError("accepted result requires trial_count")
    if result.trial_count <= 0:
        raise AcceptanceError("trial_count must be positive")
    if not result.data_audit_ids:
        raise AcceptanceError("accepted result requires at least one data_audit_id")
    if not result.policy_decision_ids:
        raise AcceptanceError("accepted result requires at least one policy_decision_id")
    if not (result.backtest_artifact_refs or result.alpha_artifact_refs):
        raise AcceptanceError("accepted result requires backtest or alpha artifacts")
    if result.best_trial:
        if not result.selection_policy:
            raise AcceptanceError("best trial display requires a selection policy")
        if result.abandoned_count <= 0 and result.rejected_count <= 0:
            raise AcceptanceError("best trial display requires abandoned/rejected count")
    return result
