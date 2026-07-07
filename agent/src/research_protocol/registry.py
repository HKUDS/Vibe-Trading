"""Filesystem protocol registry plus v1.2.1 registration review gate."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.governance.evidence_identity import canonical_json
from src.reliability.artifacts.model import ArtifactRef
from src.reliability.artifacts.store import ArtifactStore
from src.research_protocol.field_provenance import ProtocolFieldProvenance
from src.research_protocol.hashing import compute_protocol_hash
from src.research_protocol.model import ResearchProtocol as StoredResearchProtocol
from src.research_protocol.protocol_review import ProtocolReview, review_protocol_for_registration

SCHEMA_VERSION = "1.2.1"


class ProtocolRegistrationError(ValueError):
    """Raised when a protocol cannot be registered."""


class ProtocolImmutableError(ValueError):
    """Raised when a registered protocol is mutated in place."""


class ResearchProtocol(BaseModel):
    """Tolerant protocol model used by the v1.2.1 confirmation gate."""

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


class ProtocolRegistry:
    """Store draft/registered protocols without replacing GoalStore or Hypotheses."""

    def __init__(self, root: Path | None = None, *, artifact_root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path.home() / ".vibe-trading" / "research-protocols"
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifact_store = ArtifactStore(root=artifact_root) if artifact_root is not None else ArtifactStore()

    def save_draft(self, protocol: StoredResearchProtocol) -> StoredResearchProtocol:
        """Persist a draft protocol; registered protocols are immutable."""
        existing = self.get(protocol.protocol_id)
        if existing is not None and existing.status == "registered":
            raise ProtocolImmutableError(f"registered protocol is immutable: {protocol.protocol_id}")
        if protocol.status == "registered":
            raise ProtocolImmutableError("use register() to create registered protocols")
        draft = protocol.model_copy(update={"status": "draft", "protocol_hash": compute_protocol_hash(protocol)})
        self._write_protocol(draft)
        return draft

    def register(self, protocol_id: str, *, created_by: str | None = None) -> StoredResearchProtocol:
        """Register a draft protocol and write a research_protocol artifact."""
        current = self.get(protocol_id)
        if current is None:
            raise KeyError(f"protocol not found: {protocol_id}")
        if current.status == "registered":
            return current
        digest = compute_protocol_hash(current)
        registered = current.model_copy(
            update={
                "status": "registered",
                "protocol_hash": digest,
                "registered_at": datetime.now(timezone.utc),
                "created_by": created_by or current.created_by,
            }
        )
        self._write_protocol(registered)
        record = self.artifact_store.write_json(
            registered.model_dump(mode="json"),
            artifact_type="research_protocol",
            generated_by="ProtocolRegistry",
            metadata={
                "protocol_id": registered.protocol_id,
                "protocol_hash": registered.protocol_hash,
                "goal_id": registered.goal_id,
                "hypothesis_id": registered.hypothesis_id,
            },
        )
        if record is not None:
            self._write_artifact_ref(registered.protocol_hash, record.to_ref())
        return registered

    def get(self, protocol_id: str) -> StoredResearchProtocol | None:
        path = self._protocol_path(protocol_id)
        if not path.exists():
            return None
        return StoredResearchProtocol.model_validate_json(path.read_text(encoding="utf-8"))

    def is_registered(self, protocol_hash: str) -> bool:
        for path in self.root.glob("*.json"):
            protocol = StoredResearchProtocol.model_validate_json(path.read_text(encoding="utf-8"))
            if protocol.status == "registered" and protocol.protocol_hash == protocol_hash:
                return True
        return False

    def artifact_refs_for(self, protocol_hash: str) -> list[ArtifactRef]:
        path = self.root / f"{protocol_hash}.artifact_refs.json"
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [ArtifactRef.model_validate(item) for item in raw]

    def _protocol_path(self, protocol_id: str) -> Path:
        safe = "".join(ch for ch in protocol_id if ch.isalnum() or ch in {"_", "-"})
        if not safe:
            raise ValueError("protocol_id must contain a safe filename character")
        return self.root / f"{safe}.json"

    def _write_protocol(self, protocol: StoredResearchProtocol) -> None:
        path = self._protocol_path(protocol.protocol_id)
        path.write_text(protocol.model_dump_json(indent=2), encoding="utf-8")

    def _write_artifact_ref(self, protocol_hash: str, ref: ArtifactRef) -> None:
        path = self.root / f"{protocol_hash}.artifact_refs.json"
        refs = self.artifact_refs_for(protocol_hash)
        refs.append(ref)
        path.write_text(
            json.dumps([item.model_dump(mode="json") for item in refs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


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
