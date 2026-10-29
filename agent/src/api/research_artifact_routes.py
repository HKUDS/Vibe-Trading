"""HTTP routes for persistent, versioned research artifacts."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.research_artifacts import ResearchArtifactStore


class ResearchArtifactSaveRequest(BaseModel):
    """Create a series or append an explicitly linked revision."""

    artifact_id: str | None = None
    subject: str | None = Field(default=None, max_length=5000)
    universe: str | None = Field(default=None, max_length=1000)
    content: str = Field(..., min_length=1, max_length=500_000)
    data_as_of: str = Field(..., min_length=1, max_length=100)
    evidence: list[dict[str, Any]] | None = None
    verification_status: str | None = Field(default=None, max_length=100)
    completeness: str | None = Field(default=None, max_length=100)
    hypothesis_id: str | None = None
    goal_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None


def register_research_artifact_routes(app: FastAPI) -> None:
    """Mount research-artifact routes using the host authentication dependency."""
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    if host is None:
        raise RuntimeError("register_research_artifact_routes requires api_server in sys.modules")
    require_auth = host.require_auth

    @app.post(
        "/api/research-artifacts",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_auth)],
    )
    def save_research_artifact(req: ResearchArtifactSaveRequest):
        store = ResearchArtifactStore()
        try:
            result = store.save(**req.model_dump())
            return result.to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            store.close()

    @app.get("/api/research-artifacts", dependencies=[Depends(require_auth)])
    def search_research_artifacts(
        query: str = "",
        subject: str = "",
        universe: str = "",
        hypothesis_id: str = "",
        goal_id: str = "",
        session_id: str = "",
        run_id: str = "",
        limit: int = Query(default=50, ge=1, le=200),
    ):
        store = ResearchArtifactStore()
        try:
            rows = store.search(
                query=query,
                subject=subject,
                universe=universe,
                hypothesis_id=hypothesis_id,
                goal_id=goal_id,
                session_id=session_id,
                run_id=run_id,
                limit=limit,
            )
            return {"count": len(rows), "artifacts": [row.to_dict() for row in rows]}
        finally:
            store.close()

    @app.get("/api/research-artifacts/revision/{revision_id}", dependencies=[Depends(require_auth)])
    def get_research_revision(revision_id: str):
        store = ResearchArtifactStore()
        try:
            revision = store.get_revision(revision_id)
            if revision is None:
                raise HTTPException(status_code=404, detail=f"research revision not found: {revision_id}")
            return {"revision": revision.to_dict()}
        finally:
            store.close()

    @app.get("/api/research-artifacts/{artifact_id}", dependencies=[Depends(require_auth)])
    def get_research_artifact(artifact_id: str):
        store = ResearchArtifactStore()
        try:
            latest = store.get_latest(artifact_id)
            if latest is None:
                raise HTTPException(status_code=404, detail=f"research artifact not found: {artifact_id}")
            return {
                "artifact": latest.to_dict(),
                "revisions": [row.to_dict() for row in store.list_revisions(artifact_id)],
            }
        finally:
            store.close()
