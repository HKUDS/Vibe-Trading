"""IM channel HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_channels_routes(app, ...)``.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_QR_LOGIN_SESSION_TTL_S = 10 * 60


# ---------------------------------------------------------------------------
# Pydantic models (defined locally -- NO shared modules, per maintainer rule)
# ---------------------------------------------------------------------------

class ChannelPairingCommandRequest(BaseModel):
    """Pairing command payload for IM channel sender pairing."""

    channel: str
    command: str


@dataclass
class _QRLoginSession:
    channel: str
    adapter: Any
    created_at: float


# ---------------------------------------------------------------------------
# Lifecycle helpers (module-level, access host state via sys.modules)
# ---------------------------------------------------------------------------


async def _start_channel_runtime():
    """Start the IM channel runtime."""
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    runtime = host._get_channel_runtime()
    await runtime.start(start_manager=True)
    return runtime


async def _stop_channel_runtime() -> None:
    """Stop the IM channel runtime if it was initialized."""
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    if host._channel_runtime is None:
        return
    await host._channel_runtime.stop()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_channels_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
) -> None:
    """Mount the channel routes onto ``app``.

    Resolves ``require_auth`` from the host ``api_server`` module via
    ``sys.modules`` when not passed explicitly.
    """
    # Resolve host dependencies via sys.modules fallback
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")

    if host is None:
        raise RuntimeError(
            "register_channels_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    if require_auth is None:
        require_auth = host.require_auth

    # Late-access closure for monkeypatch compatibility
    def _get_channel_runtime():
        """Late-access _get_channel_runtime for test monkeypatch compat."""
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return h._get_channel_runtime()

    qr_login_sessions: dict[str, _QRLoginSession] = {}
    channel_login_sessions: dict[str, str] = {}

    async def _drop_qr_login_session(session_id: str, *, cancel: bool) -> None:
        session = qr_login_sessions.pop(session_id, None)
        if session is None:
            return
        if channel_login_sessions.get(session.channel) == session_id:
            channel_login_sessions.pop(session.channel, None)
        if cancel:
            try:
                await session.adapter.cancel_qr_login()
            except Exception:  # noqa: BLE001 - cleanup must not mask the API response
                logger.warning("Failed to clean up QR login session", exc_info=True)

    async def _expire_qr_login_sessions() -> None:
        now = time.monotonic()
        expired = [
            session_id
            for session_id, session in qr_login_sessions.items()
            if now - session.created_at >= _QR_LOGIN_SESSION_TTL_S
        ]
        for session_id in expired:
            await _drop_qr_login_session(session_id, cancel=True)

    # --- Routes ---

    @app.get("/channels/status", dependencies=[Depends(require_auth)])
    async def channels_status():
        """Return IM channel runtime and adapter status."""
        runtime = _get_channel_runtime()
        return runtime.status()

    @app.post("/channels/start", dependencies=[Depends(require_auth)])
    async def channels_start():
        """Start configured IM channel adapters."""
        await _expire_qr_login_sessions()
        if qr_login_sessions:
            raise HTTPException(status_code=409, detail="Cancel the active QR login before starting channels")
        runtime = await _start_channel_runtime()
        return {"status": "started", **runtime.status()}

    @app.post("/channels/stop", dependencies=[Depends(require_auth)])
    async def channels_stop():
        """Stop configured IM channel adapters."""
        runtime = _get_channel_runtime()
        await runtime.stop()
        return {"status": "stopped", **runtime.status()}

    @app.post("/channels/{channel}/qr-login", dependencies=[Depends(require_auth)])
    async def channels_qr_login_start(channel: str):
        """Start an authenticated, short-lived browser QR login session."""
        await _expire_qr_login_sessions()
        runtime = _get_channel_runtime()
        adapter = runtime.manager.get_channel(channel) if runtime.manager is not None else None
        if adapter is None:
            raise HTTPException(status_code=404, detail=f"Enabled channel '{channel}' is not loaded")
        if not bool(getattr(adapter, "qr_login_supported", False)):
            raise HTTPException(status_code=400, detail=f"Channel '{channel}' does not support QR login")
        if adapter.is_running:
            raise HTTPException(status_code=409, detail=f"Stop channel '{channel}' before QR login")
        if channel in channel_login_sessions:
            raise HTTPException(status_code=409, detail=f"A QR login for channel '{channel}' is already active")

        session_id = secrets.token_urlsafe(24)
        qr_login_sessions[session_id] = _QRLoginSession(
            channel=channel,
            adapter=adapter,
            created_at=time.monotonic(),
        )
        channel_login_sessions[channel] = session_id
        try:
            result = await adapter.begin_qr_login()
        except Exception as exc:  # noqa: BLE001 - external login failures become a stable API error
            logger.warning("Failed to start %s QR login", channel, exc_info=True)
            await _drop_qr_login_session(session_id, cancel=True)
            raise HTTPException(status_code=502, detail=f"Could not start QR login for '{channel}'") from exc

        response = {"channel": channel, "session_id": session_id, **result}
        if result.get("status") in {"authenticated", "expired", "failed"}:
            await _drop_qr_login_session(session_id, cancel=False)
            response.pop("session_id", None)
        return response

    @app.get("/channels/qr-login/{session_id}", dependencies=[Depends(require_auth)])
    async def channels_qr_login_status(session_id: str):
        """Advance a browser QR login without returning adapter credentials."""
        await _expire_qr_login_sessions()
        session = qr_login_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="QR login session was not found or expired")
        try:
            result = await session.adapter.poll_qr_login()
        except Exception as exc:  # noqa: BLE001 - external login failures become a stable API error
            logger.warning("Failed to poll %s QR login", session.channel, exc_info=True)
            await _drop_qr_login_session(session_id, cancel=True)
            raise HTTPException(status_code=502, detail=f"Could not poll QR login for '{session.channel}'") from exc

        response = {"channel": session.channel, "session_id": session_id, **result}
        if result.get("status") in {"authenticated", "expired", "failed"}:
            await _drop_qr_login_session(session_id, cancel=False)
            response.pop("session_id", None)
        return response

    @app.delete("/channels/qr-login/{session_id}", dependencies=[Depends(require_auth)])
    async def channels_qr_login_cancel(session_id: str):
        """Cancel a browser QR login and discard its transient challenge."""
        await _expire_qr_login_sessions()
        session = qr_login_sessions.get(session_id)
        if session is None:
            return {"status": "cancelled"}
        channel = session.channel
        await _drop_qr_login_session(session_id, cancel=True)
        return {"channel": channel, "status": "cancelled"}

    @app.post("/channels/pairing/command", dependencies=[Depends(require_auth)])
    async def channels_pairing_command(payload: ChannelPairingCommandRequest):
        """Run a pairing command against the shared pairing store."""
        from src.channels.pairing import handle_pairing_command

        return {
            "channel": payload.channel,
            "reply": handle_pairing_command(payload.channel, payload.command),
        }
