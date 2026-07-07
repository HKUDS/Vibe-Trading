"""Artifact lineage helpers."""

from __future__ import annotations

from typing import Any

from src.reliability.artifacts.store import ArtifactStore


class ArtifactGraph:
    """Query artifact lineage without exposing payload values."""

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self.artifact_store = artifact_store

    def lineage(self, artifact_id: str) -> dict[str, Any]:
        record = self.artifact_store.get_record(artifact_id)
        if record is None:
            return {"artifact_id": artifact_id, "found": False, "parents": []}
        return {
            "artifact_id": record.artifact_id,
            "artifact_type": record.artifact_type,
            "schema_version": record.schema_version,
            "sha256": record.sha256,
            "uri": record.uri,
            "parents": list(record.parent_artifacts),
            "metadata": record.metadata,
            "found": True,
        }

