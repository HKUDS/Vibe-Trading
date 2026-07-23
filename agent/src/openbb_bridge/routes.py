"""FastAPI routes exposing Vibe-Trading as an OpenBB Workspace custom agent.

Two endpoints are mandated by the OpenBB Workspace custom-agent contract:

* ``GET  /agents.json`` -- the agent manifest used for discovery.
* ``POST /v1/query``    -- the streaming query endpoint (SSE).

Both are registered onto the shared FastAPI app via
:func:`register_openbb_routes`, alongside the optional AI-service endpoints.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from openbb_ai.helpers import message_chunk, reasoning_step
from openbb_ai.models import QueryRequest
from sse_starlette.sse import EventSourceResponse

from src.api.state import _get_session_service

from .adapter import OpenBBQueryAdapter
from .ai_service_routes import register_ai_service_routes
from .models import AgentManifest

logger = logging.getLogger("openbb_bridge")

openbb_router = APIRouter(tags=["openbb-workspace"])

# The agent key must be a stable slug; Workspace uses it as the agent id.
AGENT_KEY = "vibe_trading_agent"

_MANIFEST = AgentManifest(
    name="Vibe-Trading Finance Agent",
    description=(
        "AI-powered quantitative finance research agent with backtesting, "
        "factor analysis, swarm teams, and 80+ financial tools. Supports "
        "multi-market data, strategy generation, and live trading analysis."
    ),
    image="https://raw.githubusercontent.com/HKUDS/Vibe-Trading/main/frontend/public/favicon.png",
    endpoints={"query": "/v1/query"},
    features={
        "streaming": True,
        "widget-dashboard-select": True,
        "widget-dashboard-search": True,
    },
)

# Cache one adapter per session-service instance.
_adapter_cache: Dict[int, OpenBBQueryAdapter] = {}


def _get_adapter() -> Optional[OpenBBQueryAdapter]:
    """Return an adapter bound to the current session service, or ``None``."""
    service = _get_session_service()
    if service is None:
        return None
    key = id(service)
    adapter = _adapter_cache.get(key)
    if adapter is None:
        adapter = OpenBBQueryAdapter(session_service=service)
        _adapter_cache[key] = adapter
    return adapter


@openbb_router.get("/agents.json")
def agents_manifest() -> JSONResponse:
    """Advertise Vibe-Trading as an OpenBB Workspace agent."""
    return JSONResponse(content={AGENT_KEY: _MANIFEST.model_dump()})


@openbb_router.post("/v1/query")
async def query(request: QueryRequest) -> EventSourceResponse:
    """Handle an OpenBB Workspace query and stream results back as SSE."""
    adapter = _get_adapter()

    if adapter is None:

        async def unavailable() -> AsyncGenerator[dict, None]:
            yield reasoning_step(
                message="Vibe-Trading session runtime is not enabled.",
                event_type="ERROR",
            ).model_dump()
            yield message_chunk(
                text=(
                    "The Vibe-Trading session runtime is not enabled. "
                    "Set ENABLE_SESSION_RUNTIME=true to use the OpenBB "
                    "Workspace agent."
                )
            ).model_dump()

        return EventSourceResponse(
            content=unavailable(), media_type="text/event-stream"
        )

    async def event_stream() -> AsyncGenerator[dict, None]:
        try:
            async for sse in adapter.handle_query(request):
                yield sse.model_dump()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected error while handling OpenBB query")
            yield reasoning_step(
                message=f"Internal error: {exc}", event_type="ERROR"
            ).model_dump()
            yield message_chunk(
                text=f"Sorry, an internal error occurred: {exc}"
            ).model_dump()

    return EventSourceResponse(content=event_stream(), media_type="text/event-stream")


def register_openbb_routes(app: FastAPI) -> None:
    """Register the OpenBB Workspace agent routes onto ``app``."""
    app.include_router(openbb_router)
    register_ai_service_routes(app)
    logger.info("OpenBB Workspace agent routes registered (/agents.json, /v1/query)")
