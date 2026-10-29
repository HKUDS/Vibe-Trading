"""Models for persistent, versioned research artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ResearchArtifactRevision:
    """One immutable revision in a research-artifact series."""

    revision_id: str
    artifact_id: str
    revision_number: int
    previous_revision_id: str | None
    subject: str
    universe: str
    content: str
    content_hash: str
    provenance_hash: str
    identity_hash: str
    data_as_of: str
    created_at: str
    evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    verification_status: str = "unverified"
    completeness: str = "complete"
    hypothesis_id: str | None = None
    goal_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None

    @property
    def evidence_missing(self) -> bool:
        """Whether this revision has no attached evidence references."""
        return not self.evidence

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation with explicit evidence gaps."""
        payload = asdict(self)
        payload["evidence"] = list(payload["evidence"])
        payload["evidence_missing"] = self.evidence_missing
        return payload


@dataclass(frozen=True)
class ResearchArtifactSaveResult:
    """Distinguish a new revision from an idempotent repeated save."""

    revision: ResearchArtifactRevision
    created: bool

    def to_dict(self) -> dict[str, Any]:
        return {"revision": self.revision.to_dict(), "created": self.created}
