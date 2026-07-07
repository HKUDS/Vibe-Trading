"""Draft protocol extraction and deterministic provenance helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.reliability.data.contracts import DataSetContract
from src.research_protocol.field_provenance import ProtocolFieldProvenance
from src.research_protocol.model import EvaluationPlan, ResearchProtocol, SplitSpec, UniverseSpec
from src.research_protocol.protocol_review import CORE_FIELD_PATHS


def draft_protocol_from_hypothesis(
    hypothesis: str,
    *,
    protocol_id: str = "proto_draft",
    created_by: str = "cli",
) -> ResearchProtocol:
    """Create a conservative draft protocol for CLI/manual refinement."""
    return ResearchProtocol(
        protocol_id=protocol_id,
        schema_version="1.0.0",
        status="draft",
        hypothesis=hypothesis,
        universe=UniverseSpec(asset_class="other", universe_name="unspecified"),
        data_requirements=[
            DataSetContract(
                dataset_id="unspecified",
                asset_class="other",
                frequency="1D",
                calendar="unspecified",
                fields=[],
                timezone="UTC",
            )
        ],
        split_policy=SplitSpec(method="holdout"),
        evaluation_plan=EvaluationPlan(metrics=["return", "sharpe"]),
        created_at=datetime.now(timezone.utc),
        created_by=created_by,
    )


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
