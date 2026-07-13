"""Auth helper routes — short-lived SSE tickets for browser EventSource auth.

Mounted by ``agent/api_server.py`` via ``register_auth_routes(app, ...)``.

A browser ``EventSource`` cannot send an ``Authorization`` header, so instead of
putting the long-lived API key in the SSE URL (where it leaks into browser
history, proxy/access logs, and Referer headers) the frontend exchanges the
header-authenticated key for a one-shot ticket here, then opens the stream with
``?ticket=``. The ticket store + validation live in ``src.api.security``.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_auth_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
) -> None:
    """Mount the auth helper routes onto ``app``.

    Args:
        app: The host FastAPI app.
        require_auth: Header-only auth dependency guarding ticket minting. When
            omitted it is resolved from the host ``api_server`` module via
            ``sys.modules`` (matches the other ``register_*_routes`` helpers).
    """
    if require_auth is None:
        import sys as _sys

        host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        if host is None:  # pragma: no cover — only triggers on weird import setups
            raise RuntimeError(
                "register_auth_routes: api_server module not in sys.modules; "
                "pass require_auth explicitly"
            )
        require_auth = host.require_auth

    from src.api.security import _mint_sse_ticket

    @app.post("/auth/sse-ticket", dependencies=[Depends(require_auth)])
    async def mint_sse_ticket() -> dict[str, str]:
        """Mint a single-use, ~60s ticket for a browser EventSource connection.

        Gated by the header-only ``require_auth`` dependency, so minting still
        requires the real API key in an ``Authorization`` header — never in a
        URL. The returned ticket replaces the long-lived key in the SSE query
        string and is invalidated on first use.
        """
        return {"ticket": _mint_sse_ticket()}
