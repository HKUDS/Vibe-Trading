"""Authenticated history dataset API; source fetches never run on the event loop."""

import asyncio
from datetime import date
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from .history_store import get_history_store


class HistoryRequest(BaseModel):
    codes: list[str] = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    interval: str = "5m"
    source: str = "auto"


class StorageRequest(BaseModel):
    quota_bytes: int = Field(ge=4 * 1024**2, le=10 * 1024**3)
    retention_days: int = Field(ge=1, le=365)


def register_history_routes(app, require_auth):
    async def call(method, *args, **kwargs):
        try:
            return await asyncio.to_thread(lambda: getattr(get_history_store(), method)(*args, **kwargs))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    auth = [Depends(require_auth)]

    @app.get("/data/history/storage", dependencies=auth)
    async def storage():
        return await call("settings")

    @app.put("/data/history/storage", dependencies=auth)
    async def update_storage(payload: StorageRequest):
        return await call("settings", **payload.model_dump())

    @app.post("/data/history/prune", dependencies=auth)
    async def prune():
        return await call("prune")

    @app.post("/data/history/plan", dependencies=auth)
    async def plan(payload: HistoryRequest):
        result = await call("plan", **payload.model_dump(mode="json"))
        result.pop("parts", None)
        return result

    @app.post("/data/history/jobs", dependencies=auth)
    async def create(payload: HistoryRequest):
        return await call("create", **payload.model_dump(mode="json"))

    @app.get("/data/history/jobs", dependencies=auth)
    async def jobs():
        return await call("status")

    @app.get("/data/history/jobs/{job}", dependencies=auth)
    async def status(job: str):
        return await call("status", job)

    @app.post("/data/history/jobs/{job}/resume", dependencies=auth)
    async def resume(job: str):
        return await call("start", job)

    @app.post("/data/history/jobs/{job}/cancel", dependencies=auth)
    async def cancel(job: str):
        return await call("cancel", job)

    @app.put("/data/history/jobs/{job}/pin", dependencies=auth)
    async def pin(job: str, pinned: bool):
        return await call("pin", job, pinned)

    @app.delete("/data/history/jobs/{job}", dependencies=auth)
    async def delete(job: str):
        return await call("delete", job)

    @app.get("/data/history/jobs/{job}/rows", dependencies=auth)
    async def rows(job: str, offset: int = Query(0, ge=0), limit: int = Query(1000, ge=1, le=1000)):
        return await call("read", job, offset, limit)
