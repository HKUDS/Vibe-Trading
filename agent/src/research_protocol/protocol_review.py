"""Registration review gate for research protocols."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.research_protocol.field_provenance import ProtocolFieldProvenance

SCHEMA_VERSION = "1.2.1"
TargetStatus = Literal["draft", "registered"]

CORE_FIELD_PATHS: tuple[str, ...] = (
    "hypothesis",
    "universe.asset_class",
    "split_policy.method",
    "split_policy.test_start",
    "split_policy.test_end",
    "benchmark_policy.primary",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProtocolReview(BaseModel):
    """Protocol registration review result."""

    schema_version: str = SCHEMA_VERSION
    protocol_id: str | None = None
    target_status: TargetStatus
    can_register: bool
    blocking_fields: list[str] = Field(default_factory=list)
    confirmation_required_fields: list[str] = Field(default_factory=list)
    missing_core_fields: list[str] = Field(default_factory=list)
    unconfirmed_inferred_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=_utc_now)

    @field_validator("checked_at")
    @classmethod
    def _checked_at_must_be_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        return value.astimezone(timezone.utc)


def review_protocol_for_registration(
    protocol: dict[str, Any] | Any,
    provenance: list[ProtocolFieldProvenance] | None = None,
    *,
    target_status: TargetStatus = "registered",
) -> ProtocolReview:
    """Review whether a protocol may be registered."""
    payload = _as_dict(protocol)
    provenance_by_path = _merge_provenance(provenance or [])
    missing_fields = _missing_core_fields(payload, provenance_by_path)
    unconfirmed = _unconfirmed_inferred_core_fields(provenance_by_path)
    confirmation_required = sorted(
        {
            item.field_path
            for item in provenance_by_path.values()
            if item.requires_confirmation and item.confirmation_status != "confirmed"
        }
    )
    if target_status == "draft":
        return ProtocolReview(
            protocol_id=_text(payload.get("protocol_id")),
            target_status=target_status,
            can_register=True,
            confirmation_required_fields=confirmation_required,
            missing_core_fields=missing_fields,
            unconfirmed_inferred_fields=unconfirmed,
        )
    blocking = sorted(set(missing_fields + unconfirmed))
    return ProtocolReview(
        protocol_id=_text(payload.get("protocol_id")),
        target_status=target_status,
        can_register=not blocking,
        blocking_fields=blocking,
        confirmation_required_fields=confirmation_required,
        missing_core_fields=missing_fields,
        unconfirmed_inferred_fields=unconfirmed,
    )


def _missing_core_fields(
    protocol: dict[str, Any],
    provenance_by_path: dict[str, ProtocolFieldProvenance],
) -> list[str]:
    missing: list[str] = []
    for field_path in CORE_FIELD_PATHS:
        if _is_missing(protocol, field_path) or provenance_by_path.get(field_path, None) is not None and provenance_by_path[field_path].source == "missing":
            missing.append(field_path)
    if _is_missing(protocol, "cost_model") and not bool(protocol.get("exploratory_only")):
        missing.append("cost_model")
    if _is_missing(protocol, "execution_assumptions") and not bool(protocol.get("non_tradable_exploratory")):
        missing.append("execution_assumptions")
    return sorted(set(missing))


def _unconfirmed_inferred_core_fields(
    provenance_by_path: dict[str, ProtocolFieldProvenance],
) -> list[str]:
    fields: list[str] = []
    core = set(CORE_FIELD_PATHS) | {"cost_model", "execution_assumptions"}
    for field_path, item in provenance_by_path.items():
        if field_path not in core:
            continue
        if item.source == "inferred" and item.confirmation_status != "confirmed":
            fields.append(field_path)
    return sorted(set(fields))


def _merge_provenance(items: list[ProtocolFieldProvenance]) -> dict[str, ProtocolFieldProvenance]:
    merged: dict[str, ProtocolFieldProvenance] = {}
    for item in items:
        existing = merged.get(item.field_path)
        if existing is None or _provenance_priority(item) >= _provenance_priority(existing):
            merged[item.field_path] = item
    return merged


def _provenance_priority(item: ProtocolFieldProvenance) -> int:
    if item.confirmation_status == "confirmed":
        return 4
    if item.source == "missing":
        return 3
    if item.source == "inferred":
        return 2
    if item.source == "system_default":
        return 1
    return 0


def _is_missing(protocol: dict[str, Any], field_path: str) -> bool:
    value: Any = protocol
    for part in field_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return True
        value = value[part]
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, dict) and not value:
        return True
    return False


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
