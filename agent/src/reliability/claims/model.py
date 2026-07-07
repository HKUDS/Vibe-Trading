"""Pydantic models for v1.2.1 structured research claims."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = "1.2.1"

ClaimType = Literal[
    "tradable",
    "alpha",
    "generalization",
    "paper_trade_candidate",
    "production_ready",
    "factor_novelty",
    "risk_reduction",
    "data_quality",
    "execution_realism",
]

ClaimSource = Literal["user_prompt", "assistant_final", "tool_output", "research_card", "manual_review"]


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ResearchClaim(BaseModel):
    """One structured claim that can be gated by scorecard policy."""

    schema_version: str = SCHEMA_VERSION
    claim_id: str
    claim_type: ClaimType
    claim_text: str
    source: ClaimSource
    source_ref: str | None = None
    confidence: float | None = None
    requires_gate: bool = True
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("claim_text")
    @classmethod
    def _claim_text_not_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("claim_text must not be empty")
        return text

    @field_validator("confidence")
    @classmethod
    def _confidence_between_zero_and_one(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value

    @field_validator("created_at")
    @classmethod
    def _created_at_must_be_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class ClaimSet(BaseModel):
    """Structured claims extracted for one research run."""

    schema_version: str = SCHEMA_VERSION
    claim_set_id: str
    run_id: str
    claims: list[ResearchClaim] = Field(default_factory=list)
    extractor_version: str
    generated_by: str
    artifact_ref: str | None = None


class ClaimAudit(BaseModel):
    """Validation summary for a ClaimSet."""

    schema_version: str = SCHEMA_VERSION
    run_id: str
    claim_set_id: str
    checked_claim_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def _created_at_must_be_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)
