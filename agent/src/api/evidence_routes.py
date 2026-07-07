"""Read-only evidence closure API routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from src.governance.evidence_index import EvidenceIndexStore
from src.governance.evidence_outbox import EvidenceOutbox
from src.reliability.artifacts.graph import ArtifactGraph
from src.reliability.artifacts.store import ArtifactStore
from src.reliability.artifacts.verifier import EvidenceVerifier


def register_evidence_routes(app: FastAPI, *, auth_dependency=None) -> None:
    """Register v1.2.1 read-only evidence routes."""
    dependencies = [Depends(auth_dependency)] if auth_dependency is not None else []

    @app.get("/research/evidence/{run_id}", dependencies=dependencies)
    async def get_research_evidence(run_id: str):
        index = EvidenceIndexStore().get(run_id)
        if index is None:
            report = EvidenceVerifier(
                artifact_store=ArtifactStore(),
                index_store=EvidenceIndexStore(),
                outbox=EvidenceOutbox(),
            ).verify(run_id)
            return {
                "schema_version": "1.2.1",
                "run_id": run_id,
                "index": None,
                "degraded": report.degraded,
                "degraded_reasons": report.degraded_reasons,
                "verified_from": report.verified_from,
            }
        return index.model_dump(mode="json")

    @app.get("/research/evidence/{run_id}/verify", dependencies=dependencies)
    async def verify_research_evidence(run_id: str):
        report = EvidenceVerifier(
            artifact_store=ArtifactStore(),
            index_store=EvidenceIndexStore(),
            outbox=EvidenceOutbox(),
        ).verify(run_id)
        return report.model_dump(mode="json")

    @app.get("/research/artifacts/{artifact_id}/lineage", dependencies=dependencies)
    async def get_artifact_lineage(artifact_id: str):
        lineage = ArtifactGraph(ArtifactStore()).lineage(artifact_id)
        if not lineage.get("found"):
            raise HTTPException(status_code=404, detail="artifact not found")
        return lineage
