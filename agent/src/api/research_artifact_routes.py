"""HTTP routes for persistent, versioned research artifacts."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from src.research_artifacts import ResearchArtifactStore

# The content field already caps the conclusion; evidence references and ids
# were unbounded, so one authenticated request could store an arbitrarily
# large row.
_MAX_EVIDENCE_ITEMS = 1000
_MAX_EVIDENCE_CHARS = 1_000_000


class ResearchArtifactSaveRequest(BaseModel):
    """Create a series or append an explicitly linked revision."""

    artifact_id: str | None = Field(default=None, max_length=200)
    subject: str | None = Field(default=None, max_length=5000)
    universe: str | None = Field(default=None, max_length=1000)
    content: str = Field(..., min_length=1, max_length=500_000)
    data_as_of: str = Field(..., min_length=1, max_length=100)
    evidence: list[dict[str, Any]] | None = Field(default=None, max_length=_MAX_EVIDENCE_ITEMS)
    verification_status: str | None = Field(default=None, max_length=100)
    completeness: str | None = Field(default=None, max_length=100)
    hypothesis_id: str | None = Field(default=None, max_length=200)
    goal_id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    run_id: str | None = Field(default=None, max_length=200)

    @field_validator("evidence")
    @classmethod
    def _bound_evidence_size(cls, value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if value is not None and len(json.dumps(value, ensure_ascii=False, default=str)) > _MAX_EVIDENCE_CHARS:
            raise ValueError(f"evidence must serialize to at most {_MAX_EVIDENCE_CHARS} characters")
        return value


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

    @app.get("/api/research-artifacts/{artifact_id}/export", dependencies=[Depends(require_auth)])
    def export_research_artifact(
        artifact_id: str,
        format: Literal["json", "markdown"] = Query(default="json"),
        from_revision_id: str | None = Query(default=None, min_length=1, max_length=200),
        to_revision_id: str | None = Query(default=None, min_length=1, max_length=200),
    ):
        store = ResearchArtifactStore()
        try:
            if (from_revision_id is None) != (to_revision_id is None):
                raise HTTPException(
                    status_code=400,
                    detail="from_revision_id and to_revision_id must be provided together",
                )
            if from_revision_id is not None and to_revision_id is not None:
                return store.export_comparison(
                    artifact_id=artifact_id,
                    from_revision_id=from_revision_id,
                    to_revision_id=to_revision_id,
                    format=format,
                ).to_dict()
            return store.export_series(artifact_id, format).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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

    @app.get("/api/research-artifacts/{artifact_id}/compare", dependencies=[Depends(require_auth)])
    def compare_research_revisions(
        artifact_id: str,
        from_revision_id: str = Query(min_length=1, max_length=200),
        to_revision_id: str = Query(min_length=1, max_length=200),
    ):
        store = ResearchArtifactStore()
        try:
            comparison = store.compare_revisions(
                artifact_id=artifact_id,
                from_revision_id=from_revision_id,
                to_revision_id=to_revision_id,
            )
            return {"comparison": comparison}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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
