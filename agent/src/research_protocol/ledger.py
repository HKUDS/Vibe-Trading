"""Protocol review ledger events for confirmation records."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.governance.evidence_identity import canonical_json

SCHEMA_VERSION = "1.2.1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProtocolLedgerEvent(BaseModel):
    """Hash-addressed protocol confirmation event."""

    schema_version: str = SCHEMA_VERSION
    event_type: str = "protocol_field_confirmed"
    protocol_id: str
    field_path: str
    confirmed_by: str
    value_hash: str
    event_hash: str
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at")
    @classmethod
    def _created_at_must_be_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)


def record_protocol_field_confirmation(
    *,
    protocol_id: str,
    field_path: str,
    value: Any,
    confirmed_by: str,
) -> ProtocolLedgerEvent:
    """Create a deterministic confirmation event suitable for ledger/artifact storage."""
    value_hash = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    envelope = {
        "event_type": "protocol_field_confirmed",
        "protocol_id": protocol_id,
        "field_path": field_path,
        "confirmed_by": confirmed_by,
        "value_hash": value_hash,
    }
    event_hash = hashlib.sha256(canonical_json(envelope).encode("utf-8")).hexdigest()
    return ProtocolLedgerEvent(
        protocol_id=protocol_id,
        field_path=field_path,
        confirmed_by=confirmed_by,
        value_hash=value_hash,
        event_hash=event_hash,
    )
