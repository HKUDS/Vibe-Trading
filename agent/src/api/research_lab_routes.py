"""Authenticated, bounded research jobs with durable reports and polling."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from src.research_lab import service

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
    async def report(job_id: str):
        try:
            state = service.get_job(job_id)
        except (ValueError, OSError) as exc:
            raise HTTPException(404, str(exc)) from exc
        if state["status"] != "completed":
            raise HTTPException(409, "research report is not complete")
        return state["result"]
