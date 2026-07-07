"""Deterministic protocol provenance extraction."""

from __future__ import annotations

from typing import Any

from src.research_protocol.field_provenance import ProtocolFieldProvenance
from src.research_protocol.protocol_review import CORE_FIELD_PATHS


def extract_protocol_provenance(protocol: dict[str, Any]) -> list[ProtocolFieldProvenance]:
    """Mark required protocol fields as explicit or missing without inventing user intent."""
    provenance: list[ProtocolFieldProvenance] = []
    for field_path in CORE_FIELD_PATHS:
        if _has_value(protocol, field_path):
            provenance.append(
                ProtocolFieldProvenance(
                    field_path=field_path,
                    source="explicit_user",
                    confirmation_status="not_required",
                )
            )
        else:
            provenance.append(
                ProtocolFieldProvenance(
                    field_path=field_path,
                    source="missing",
                    requires_confirmation=True,
                    confirmation_status="pending",
                )
            )
    for field_path, exemption in (
        ("cost_model", "exploratory_only"),
        ("execution_assumptions", "non_tradable_exploratory"),
    ):
        if _has_value(protocol, field_path) or bool(protocol.get(exemption)):
            provenance.append(
                ProtocolFieldProvenance(
                    field_path=field_path,
                    source="explicit_user",
                    confirmation_status="not_required",
                )
            )
        else:
            provenance.append(
                ProtocolFieldProvenance(
                    field_path=field_path,
                    source="missing",
                    requires_confirmation=True,
                    confirmation_status="pending",
                )
            )
    return provenance


def _has_value(protocol: dict[str, Any], field_path: str) -> bool:
    value: Any = protocol
    for part in field_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(value)
    return True
