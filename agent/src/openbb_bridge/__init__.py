"""OpenBB Workspace bridge for Vibe-Trading.

This package exposes Vibe-Trading's :class:`AgentLoop` as an OpenBB Workspace
custom agent. It is a non-invasive adapter layer: it does not modify any of
Vibe-Trading's core components (AgentLoop, ToolRegistry, SessionService) and can
be enabled or removed independently of the rest of the API server.

Use :func:`register_openbb_routes` to mount the endpoints onto a FastAPI app.
"""

from __future__ import annotations

from .adapter import OpenBBQueryAdapter
from .context_injector import WidgetContextInjector
from .event_mapper import SSEEventMapper
from .models import AgentManifest, SessionMapping
from .routes import register_openbb_routes

__all__ = [
    "register_openbb_routes",
    "OpenBBQueryAdapter",
    "WidgetContextInjector",
    "SSEEventMapper",
    "AgentManifest",
    "SessionMapping",
]
