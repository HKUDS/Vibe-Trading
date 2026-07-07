"""Research protocol model, hash semantics, and registration gate."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.governance.evidence_identity import canonical_json
from src.research_protocol.field_provenance import ProtocolFieldProvenance
from src.research_protocol.protocol_review import ProtocolReview, review_protocol_for_registration

SCHEMA_VERSION = "1.2.1"


class ProtocolRegistrationError(ValueError):
    """Raised when a protocol cannot be registered."""


class ResearchProtocol(BaseModel):
    """Tolerant research protocol model.

    Provenance is explicitly excluded from the canonical protocol hash.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: str = SCHEMA_VERSION
    protocol_id: str | None = None
    status: Literal["draft", "registered"] = "draft"
    hypothesis: str | None = None
    universe: dict[str, Any] = Field(default_factory=dict)
    split_policy: dict[str, Any] = Field(default_factory=dict)
    benchmark_policy: dict[str, Any] = Field(default_factory=dict)
    cost_model: dict[str, Any] | None = None
    execution_assumptions: dict[str, Any] | None = None
    exploratory_only: bool = False
    non_tradable_exploratory: bool = False
    provenance: list[ProtocolFieldProvenance] = Field(default_factory=list)


class RegisteredProtocol(BaseModel):
    """Registered protocol plus review and canonical hash."""

    schema_version: str = SCHEMA_VERSION
    protocol: ResearchProtocol
    status: Literal["registered"] = "registered"
    protocol_hash: str
    review: ProtocolReview


def protocol_hash(protocol: ResearchProtocol | dict[str, Any]) -> str:
    """Compute a canonical protocol hash excluding provenance metadata."""
    model = protocol if isinstance(protocol, ResearchProtocol) else ResearchProtocol.model_validate(protocol)
    payload = model.model_dump(mode="json", exclude={"provenance", "status"})
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def register_protocol(
    protocol: ResearchProtocol | dict[str, Any],
    provenance: list[ProtocolFieldProvenance] | None = None,
) -> RegisteredProtocol:
    """Register a protocol only after confirmation review passes."""
    model = protocol if isinstance(protocol, ResearchProtocol) else ResearchProtocol.model_validate(protocol)
    provenance_items = provenance if provenance is not None else model.provenance
    review = review_protocol_for_registration(
        model.model_dump(mode="json"),
        provenance_items,
        target_status="registered",
    )
    if not review.can_register:
        fields = ", ".join(review.blocking_fields)
        raise ProtocolRegistrationError(f"protocol registration blocked by fields: {fields}")
    registered = model.model_copy(update={"status": "registered", "provenance": list(provenance_items)})
    return RegisteredProtocol(
        protocol=registered,
        protocol_hash=protocol_hash(registered),
        review=review,
    )
