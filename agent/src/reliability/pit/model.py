"""PIT timestamp model."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, field_validator


class PITTimestampSet(BaseModel):
    """The five timestamps used for PIT checks."""

    effective_at: datetime | None = None
    published_at: datetime | None = None
    ingested_at: datetime | None = None
    available_at: datetime | None = None
    as_of: datetime | None = None

    @field_validator("effective_at", "published_at", "ingested_at", "available_at", "as_of")
    @classmethod
    def _datetime_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("PIT timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)
