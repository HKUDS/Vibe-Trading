"""Point-in-time checks for data availability."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

from src.reliability.data.contracts import StructuredWarning
from src.reliability.pit.model import PITTimestampSet
from src.reliability.pit.violations import PITViolation

DatasetKind = Literal["ohlcv", "event", "fundamental", "news", "macro", "sec_filing", "other"]
_AVAILABLE_AT_REQUIRED = {"event", "fundamental", "news", "macro", "sec_filing"}


class PITCheckResult(BaseModel):
    """PIT check result."""

    pit_safe: bool
    warnings: list[StructuredWarning] = Field(default_factory=list)
    violations: list[PITViolation] = Field(default_factory=list)
    timestamps: PITTimestampSet


class PITChecker:
    """Check PIT timestamp sets against an optional as-of."""

    def __init__(self, *, dataset_kind: DatasetKind = "ohlcv", as_of: datetime | None = None) -> None:
        self.dataset_kind = dataset_kind
        self.as_of = _to_utc(as_of) if as_of is not None else None

    def check(self, timestamps: PITTimestampSet) -> PITCheckResult:
        """Check timestamps for PIT warnings and hard failures."""
        as_of = timestamps.as_of or self.as_of
        available_at = timestamps.available_at
        warnings: list[StructuredWarning] = []
        violations: list[PITViolation] = []
        pit_safe = True

        if as_of is None:
            warnings.append(
                StructuredWarning(
                    code="PIT_MISSING_AS_OF",
                    severity="warning",
                    message="as_of timestamp is missing; PIT safety cannot be fully asserted",
                )
            )

        if available_at is None and self.dataset_kind in _AVAILABLE_AT_REQUIRED:
            warnings.append(
                StructuredWarning(
                    code="PIT_AVAILABLE_AT_MISSING",
                    severity="warning",
                    message="available_at is required for event/fundamental/news/macro/filing data",
                    metadata={"dataset_kind": self.dataset_kind},
                )
            )
            pit_safe = False

        if available_at is None and self.dataset_kind == "ohlcv" and timestamps.effective_at is not None:
            available_at = _infer_ohlcv_available_at(timestamps.effective_at)
            warnings.append(
                StructuredWarning(
                    code="PIT_AVAILABLE_AT_INFERRED",
                    severity="warning",
                    message="daily OHLCV available_at inferred from effective_at",
                    metadata={"available_at": available_at.isoformat()},
                )
            )

        if available_at is not None and as_of is not None and available_at > as_of:
            violations.append(
                PITViolation(
                    code="PIT_FUTURE_DATA",
                    severity="hard_failure",
                    message="available_at is after as_of",
                    hard_failure=True,
                    metadata={"available_at": available_at.isoformat(), "as_of": as_of.isoformat()},
                )
            )
            pit_safe = False

        return PITCheckResult(
            pit_safe=pit_safe,
            warnings=warnings,
            violations=violations,
            timestamps=PITTimestampSet(
                effective_at=timestamps.effective_at,
                published_at=timestamps.published_at,
                ingested_at=timestamps.ingested_at,
                available_at=available_at,
                as_of=as_of,
            ),
        )


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def _infer_ohlcv_available_at(effective_at: datetime) -> datetime:
    return effective_at.astimezone(timezone.utc) + timedelta(days=1)
