"""Authenticated, bounded research jobs with durable reports and polling."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict

from src.research_lab import service
from src.research_lab.exports import build_walk_forward_folds_csv

_TASKS: set[asyncio.Task] = set()
_MAX_WORKERS = 2


class StudySubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    request: dict[str, Any]


def register_research_lab_routes(app: FastAPI, require_auth, require_write_auth) -> None:
    """Mount a single catalog/job API backed by the CLI's shared service."""

    @app.get("/api/research-lab/catalog", dependencies=[Depends(require_auth)])
    async def catalog():
        return await asyncio.to_thread(service.catalog)

    @app.post("/api/research-lab/jobs", dependencies=[Depends(require_write_auth)], status_code=202)
    async def submit(payload: StudySubmission):
        if len(_TASKS) >= _MAX_WORKERS:
            raise HTTPException(429, "Two research jobs are already running; retry after one finishes")
        try:
            state = service.create_job(payload.action, payload.request)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
        task = asyncio.create_task(asyncio.to_thread(service.execute_job, state["id"]))
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
        return state

    @app.get("/api/research-lab/jobs/{job_id}", dependencies=[Depends(require_auth)])
    async def get_job(job_id: str):
        try:
            return await asyncio.to_thread(service.get_job, job_id)
        except (ValueError, OSError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/research-lab/jobs/{job_id}/report", dependencies=[Depends(require_auth)])
    async def report(job_id: str, format: Literal["json", "oos_equity_csv", "folds_csv"] = "json"):
        try:
            state = service.get_job(job_id)
        except (ValueError, OSError) as exc:
            raise HTTPException(404, str(exc)) from exc
        if state["status"] != "completed":
            raise HTTPException(409, "research report is not complete")
        if format == "json":
            return state["result"]
        if format == "folds_csv":
            if state["action"] != "walk_forward":
                raise HTTPException(422, "Fold export is only available for walk-forward jobs")
            try:
                content = build_walk_forward_folds_csv(state["result"])
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(422, str(exc)) from exc
            return Response(
                content,
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="research-{job_id}-folds.csv"'},
            )
        if state["action"] != "walk_forward":
            raise HTTPException(422, "OOS equity export is only available for walk-forward jobs")
        artifact = service.job_root(job_id) / "oos_equity.csv"
        if not artifact.is_file():
            raise HTTPException(409, "OOS equity artifact is unavailable; rerun the walk-forward job")
        return FileResponse(
            artifact,
            media_type="text/csv",
            filename=f"research-{job_id}-oos-equity.csv",
        )
