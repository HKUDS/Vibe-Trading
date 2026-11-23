"""Authenticated gateway routes plus a loopback-only development entry point."""

import asyncio
from contextlib import asynccontextmanager
from typing import Callable
from datetime import date

from fastapi import Depends, FastAPI, Query, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from . import get_gateway
from .streams import StreamHub, Topic


class BarsRequest(BaseModel):
    codes: list[str] = Field(min_length=1, max_length=8)
    start_date: date
    end_date: date
    interval: str = Field(default="1D", max_length=5)
    max_rows: int = Field(default=100, ge=1, le=1000)
    source: str = Field(default="auto", max_length=32)

    @model_validator(mode="after")
    def dates_in_order(self):
        from backtest.loaders.registry import VALID_SOURCES

        if self.source not in VALID_SOURCES or self.source == "local":
            raise ValueError("Expected a registered public or configured market source")
        if self.end_date < self.start_date or (self.end_date - self.start_date).days > 3660:
            raise ValueError("Expected an ordered date range of at most ten years")
        if any(not c.strip() or len(c) > 64 or c.startswith("local:") for c in self.codes):
            raise ValueError("Expected public market symbols")
        return self


class ScanRequest(BarsRequest):
    codes: list[str] = Field(min_length=1, max_length=10000)


def register_gateway_routes(app: FastAPI, require_auth: Callable):
    """Mount capability and local-storage APIs using the host application's auth."""

    from .history_api import register_history_routes

    register_history_routes(app, require_auth)
    hub = None

    def get_hub():
        nonlocal hub
        if hub is None:
            hub = StreamHub(get_gateway())
        return hub

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        from .history_store import close_history_store, start_history_recovery

        async with original_lifespan(application):
            try:
                await asyncio.to_thread(start_history_recovery)
                yield
            finally:
                await asyncio.to_thread(close_history_store)
                if hub is not None:
                    await hub.close()

    app.router.lifespan_context = lifespan

    @app.get("/data/stream", dependencies=[Depends(require_auth)])
    async def stream(request: Request, topics: str = Query(min_length=1, max_length=1024)):
        try:
            parsed = [Topic.parse(topic) for topic in topics.split(",")]
            manager = get_hub()
            listener = manager.subscribe(parsed)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return StreamingResponse(
            manager.events(listener, request.is_disconnected),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/data/subscriptions", dependencies=[Depends(require_auth)])
    async def subscriptions():
        return get_hub().status()

    @app.get("/data/options", dependencies=[Depends(require_auth)])
    async def options(
        ticker: str = Query(min_length=1, max_length=16),
        expiration: int | None = Query(None, gt=0),
        allow_stale: bool = True,
        full: bool = False,
    ):
        result = await asyncio.to_thread(
            get_gateway().options_chain, ticker, expiration, allow_stale=allow_stale, full=full
        )
        return JSONResponse(result, status_code=200 if result.get("ok") else 503)

    @app.get("/data/capabilities", dependencies=[Depends(require_auth)])
    async def capabilities():
        from .catalog import capabilities as describe

        return await asyncio.to_thread(describe, get_gateway().config)

    @app.get("/data/status", dependencies=[Depends(require_auth)])
    async def status():
        return await asyncio.to_thread(get_gateway().status)

    @app.post("/data/bars", dependencies=[Depends(require_auth)])
    async def bars(payload: BarsRequest):
        result = await asyncio.to_thread(get_gateway().bars, **payload.model_dump(mode="json"), include_provenance=True)
        return JSONResponse(result, status_code=200 if result.get("ok") else 503)

    @app.post("/data/scans", dependencies=[Depends(require_auth)])
    async def create_scan(payload: ScanRequest):
        try:
            return get_gateway().scan_queue().create(**payload.model_dump(mode="json"))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/data/scans", dependencies=[Depends(require_auth)])
    async def scans():
        return get_gateway().scan_queue().status()

    @app.get("/data/scans/{identity}", dependencies=[Depends(require_auth)])
    async def scan_status(identity: str):
        try:
            return get_gateway().scan_queue().status(identity)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/data/scans/{identity}/cancel", dependencies=[Depends(require_auth)])
    async def cancel_scan(identity: str):
        try:
            return get_gateway().scan_queue().cancel(identity)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
