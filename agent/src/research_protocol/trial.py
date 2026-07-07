"""Trial ledger event models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


TRIAL_EVENT_SCHEMA_VERSION = "1.0.0"


class TrialEventType(str, Enum):
    PROTOCOL_REGISTERED = "protocol_registered"
    TRIAL_STARTED = "trial_started"
    DATA_LOADED = "data_loaded"
    TOOL_CALLED = "tool_called"
    POLICY_DECISION_RECORDED = "policy_decision_recorded"
    BACKTEST_COMPLETED = "backtest_completed"
    ALPHA_BENCH_COMPLETED = "alpha_bench_completed"
    SCORECARD_GENERATED = "scorecard_generated"
    RESEARCH_CARD_GENERATED = "research_card_generated"
    TRIAL_ACCEPTED = "trial_accepted"
    TRIAL_REJECTED = "trial_rejected"
    TRIAL_ABANDONED = "trial_abandoned"


class TrialEvent(BaseModel):
    """One immutable event in the trial hash chain."""

    event_id: str = Field(default_factory=lambda: f"te_{uuid4().hex}")
    event_type: TrialEventType
    schema_version: str = TRIAL_EVENT_SCHEMA_VERSION
    protocol_hash: str
    sequence_number: int
    previous_event_hash: str | None = None
    event_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)

    @field_validator("created_at")
    @classmethod
    def _created_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class LedgerVerificationResult(BaseModel):
    valid: bool
    event_count: int
    errors: list[str] = Field(default_factory=list)
