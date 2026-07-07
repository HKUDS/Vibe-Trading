"""Pydantic contracts for Phase 2 data reliability audits."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.reliability.artifacts.model import ArtifactRef
from src.reliability.pit.violations import PITViolation


class StructuredWarning(BaseModel):
    """Stable warning or hard-failure code with metadata."""

    code: str
    severity: Literal["info", "warning", "hard_failure"] = "warning"
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataSetContract(BaseModel):
    """Dataset contract describing what was requested."""

    dataset_id: str
    asset_class: Literal["ashare", "us_equity", "hk_equity", "crypto", "futures", "macro", "other"]
    frequency: str
    calendar: str
    fields: list[str]
    timezone: str
    corporate_action_policy: str | None = None
    survivorship_policy: str | None = None


class DataAccessContract(BaseModel):
    """Access contract recording source/fallback/cache provenance."""

    source: str
    selected_source: str
    request_params_hash: str
    fallback_chain: list[str]
    cache_key: str | None = None
    fetched_at: datetime
    source_timestamp: datetime | None = None
    explicit_local: bool
    source_priority_rank: int | None = None
    fallback_chain_id: str | None = None
    circuit_breaker_state: Literal["CLOSED", "OPEN", "HALF_OPEN"] | None = None
    loader_latency_ms: float | None = None

    @field_validator("fetched_at", "source_timestamp")
    @classmethod
    def _datetime_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime fields must be timezone-aware")
        return value.astimezone(timezone.utc)


class CircuitBreakerSnapshot(BaseModel):
    """Serializable source circuit-breaker state."""

    source: str
    state: Literal["CLOSED", "OPEN", "HALF_OPEN"]
    consecutive_failures: int
    opened_at: datetime | None = None
    last_error_class: str | None = None
    next_probe_after: datetime | None = None

    @field_validator("opened_at", "next_probe_after")
    @classmethod
    def _datetime_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime fields must be timezone-aware")
        return value.astimezone(timezone.utc)


class DataAuditReport(BaseModel):
    """Data reliability audit produced by an audited loader call."""

    model_config = ConfigDict(arbitrary_types_allowed=False)

    audit_id: str
    schema_version: str
    dataset_contract: DataSetContract | None = None
    access_contract: DataAccessContract
    row_count: int
    symbol_count: int
    field_coverage: dict[str, float]
    content_sample_hash: str | None = None
    per_symbol_hashes: dict[str, str] = Field(default_factory=dict)
    pit_violations: list[PITViolation] = Field(default_factory=list)
    quality_warnings: list[StructuredWarning] = Field(default_factory=list)
    market_rule_warnings: list[StructuredWarning] = Field(default_factory=list)
    source_circuit_states: dict[str, Literal["CLOSED", "OPEN", "HALF_OPEN"]] = Field(default_factory=dict)
    circuit_breaker_events: list[CircuitBreakerSnapshot] = Field(default_factory=list)
    all_sources_open: bool = False
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
