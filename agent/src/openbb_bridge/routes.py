"""FastAPI routes exposing Vibe-Trading as an OpenBB Workspace custom agent.

Two endpoints make up the OpenBB Workspace custom-agent contract:

* ``GET  /agents.json`` -- the agent manifest used for discovery. Static
  metadata only (name, description, avatar URL, endpoint, feature flags), so it
  stays unauthenticated like the other discovery surfaces; nothing about a user,
  a session, or a run is reachable through it.
* ``POST /v1/query``    -- the streaming query endpoint (SSE). This one reaches
  the full agent registry, so it carries the same ``require_auth`` dependency as
  ``POST /sessions/{id}/messages``.

Both are registered onto the shared FastAPI app via
:func:`register_openbb_routes`, which resolves auth dependencies from the host
``api_server`` module the same way the other route modules do.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Dict, Optional
from urllib.parse import urljoin

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from openbb_ai.helpers import message_chunk, reasoning_step
from openbb_ai.models import QueryRequest
from sse_starlette.sse import EventSourceResponse

from src.api.state import _get_session_service

from .adapter import OpenBBQueryAdapter
from .models import AgentManifest

logger = logging.getLogger("openbb_bridge")

# The agent key must be a stable slug; Workspace uses it as the agent id.
AGENT_KEY = "vibe_trading_agent"

QUERY_PATH = "/v1/query"

_MANIFEST = AgentManifest(
    name="Vibe-Trading Finance Agent",
    description=(
        "AI-powered quantitative finance research agent with backtesting, "
        "factor analysis, swarm teams, and a broad multi-market financial tool "
        "library covering data, strategy generation, and trade analysis."
    ),
    image="https://raw.githubusercontent.com/HKUDS/Vibe-Trading/main/frontend/public/favicon.png",
    endpoints={"query": QUERY_PATH},
    features={
        # SSE streaming: implemented by the adapter's event mapper.
        "streaming": True,
        # Explicitly selected widgets arrive in ``widgets.primary`` and their
        # names / parameters are injected into the prompt.
        "widget-dashboard-select": True,
        # Dashboard-wide widget discovery would only be useful with the
        # ``get_widget_data`` retrieval round trip (yield a function call, close
        # the stream, wait for a follow-up request). That is not implemented, so
        # the flag stays off rather than advertising data the agent never fetches.
        "widget-dashboard-search": False,
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


def register_openbb_routes(app: FastAPI) -> None:
    """Mount the OpenBB Workspace agent routes onto ``app``.

    Resolves shared auth dependencies from the host ``api_server`` module via
    ``sys.modules``, mirroring ``register_sessions_routes``.

    Args:
        app: The FastAPI application to mount onto.

    Raises:
        RuntimeError: If ``api_server`` has not been imported yet.
    """
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    if host is None:
        raise RuntimeError(
            "register_openbb_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    require_auth = host.require_auth

    @app.get("/agents.json")
    def agents_manifest(request: Request) -> JSONResponse:
        """Advertise Vibe-Trading as an OpenBB Workspace agent.

        ``endpoints.query`` is resolved against the URL the manifest was fetched
        through, because Workspace stores it verbatim and calls it directly.
        """
        manifest = _MANIFEST.model_dump()
        manifest["endpoints"] = {
            "query": urljoin(str(request.base_url), QUERY_PATH.lstrip("/"))
        }
        return JSONResponse(content={AGENT_KEY: manifest})

    @app.post(QUERY_PATH, dependencies=[Depends(require_auth)])
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

        return EventSourceResponse(
            content=event_stream(), media_type="text/event-stream"
        )

    logger.info(
        "OpenBB Workspace agent routes registered (/agents.json, %s)", QUERY_PATH
    )
