"""OpenBB Workspace bridge for Vibe-Trading.

This package exposes Vibe-Trading's :class:`AgentLoop` as an OpenBB Workspace
custom agent. It is a non-invasive adapter layer: it does not modify any of
Vibe-Trading's core components (AgentLoop, ToolRegistry, SessionService) and can
be enabled or removed independently of the rest of the API server.

The ``openbb-ai`` SDK ships in the optional ``openbb`` extra::

    pip install "vibe-trading-ai[openbb]"

Nothing here imports that SDK at module level, so ``api_server`` can call
:func:`try_register_openbb_routes` unconditionally and stay a thin assembler —
the guarded import and its operator messaging live in this package instead.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("openbb_bridge")

__all__ = ["try_register_openbb_routes"]


def try_register_openbb_routes(app: Any) -> bool:
    """Mount the OpenBB Workspace routes when the optional extra is installed.

    Args:
        app: The FastAPI application to mount onto.

    Returns:
        ``True`` when ``/agents.json`` and ``/v1/query`` were registered,
        ``False`` when the bridge stayed disabled. Never raises: a broken
        optional integration must not take down the core API.
    """
    try:
        from .routes import register_openbb_routes
    except ModuleNotFoundError as exc:
        logger.info(
            'OpenBB Workspace bridge disabled (%s). Install with: '
            'pip install "vibe-trading-ai[openbb]"',
            exc,
        )
        return False
    except Exception as exc:
        # SDK present but unusable (version skew, broken install): still fail open.
        logger.warning("OpenBB Workspace bridge failed to import: %s", exc)
        return False

    try:
        register_openbb_routes(app)
    except Exception as exc:
        logger.warning("OpenBB Workspace bridge not registered: %s", exc)
        return False
    return True
