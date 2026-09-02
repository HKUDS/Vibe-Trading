"""IM channel HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_channels_routes(app, ...)``.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic models (defined locally -- NO shared modules, per maintainer rule)
# ---------------------------------------------------------------------------

class ChannelPairingCommandRequest(BaseModel):
    """Pairing command payload for IM channel sender pairing."""

    channel: str
    command: str


class ChannelConfigUpdateRequest(BaseModel):
    """Per-channel enable/token/allowlist update for the Settings UI."""

    channel: str = Field(min_length=1, max_length=64)
    enabled: bool
    token: str | None = Field(default=None, max_length=2000)
    allowlist: str | None = Field(default=None, max_length=4000)


class ChannelConfigTestRequest(BaseModel):
    """Connectivity probe inputs for one channel."""

    channel: str = Field(min_length=1, max_length=64)
    token: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------
# Channel config helpers (agent.json is the single source of truth)
# ---------------------------------------------------------------------------

_CHANNEL_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_SECRET_KEYS = frozenset(
    {"token", "secret", "app_secret", "api_key", "apikey", "password", "webhook_secret"}
)
_ALLOWLIST_KEYS = ("allowFrom", "allow_from", "allowlist", "allowList")


def _agent_config_path():
    from src.config.paths import get_config_path

    return get_config_path()


def _read_agent_config_payload() -> dict[str, Any]:
    from src.config.loader import _read_config_file

    path = _agent_config_path()
    if not path.exists():
        return {}
    payload = _read_config_file(path)
    return payload if isinstance(payload, dict) else {}


def _write_agent_config_payload(payload: dict[str, Any]) -> None:
    path = _agent_config_path()
    if path.suffix.lower() != ".json":
        raise ValueError("Channel configuration requires a JSON agent config (~/.vibe-trading/agent.json)")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(temporary):
            os.unlink(temporary)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _redacted_channel_summary(name: str, section: dict[str, Any] | None, availability: dict[str, Any]) -> dict[str, Any]:
    section = section if isinstance(section, dict) else {}
    token_configured = any(
        key in section and str(section.get(key) or "").strip() for key in _SECRET_KEYS
    )
    allowlist: list[str] = []
    for key in _ALLOWLIST_KEYS:
        raw = section.get(key)
        if isinstance(raw, list):
            allowlist = [str(item) for item in raw]
            break
        if isinstance(raw, str) and raw.strip():
            allowlist = [item.strip() for item in raw.split(",") if item.strip()]
            break
    return {
        "channel": name,
        "display_name": availability.get("display_name", name),
        "available": availability.get("available", False),
        "error": availability.get("error", ""),
        "install_hint": availability.get("install_hint", ""),
        "configured": bool(section),
        "enabled": bool(section.get("enabled", False)),
        "token_configured": token_configured,
        "allowlist": allowlist,
    }


def _apply_channel_update(
    payload: dict[str, Any],
    *,
    channel: str,
    enabled: bool,
    token: str | None,
    allowlist: str | None,
) -> dict[str, Any]:
    channels = payload.setdefault("channels", {})
    if not isinstance(channels, dict):
        raise ValueError("agent config 'channels' must be an object")
    section = channels.setdefault(channel, {})
    if not isinstance(section, dict):
        raise ValueError(f"agent config 'channels.{channel}' must be an object")
    section["enabled"] = enabled
    if token is not None and token.strip():
        section["token"] = token.strip()
    if allowlist is not None and allowlist.strip():
        section["allowFrom"] = [item.strip() for item in allowlist.split(",") if item.strip()]
    _write_agent_config_payload(payload)
    return section


async def _probe_channel(channel: str, token: str | None) -> dict[str, Any]:
    from src.channels.registry import inspect_channel

    availability = inspect_channel(channel).to_dict()
    checks: dict[str, Any] = {
        "adapter_available": bool(availability.get("available")),
        "token_present": bool((token or "").strip()),
        "live_probe": "none",
    }
    if channel == "telegram":
        probe_token = (token or "").strip()
        if not probe_token:
            raise ValueError("Telegram probe requires a bot token")
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(f"https://api.telegram.org/bot{probe_token}/getMe")
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ValueError("Telegram probe failed: could not reach the Bot API") from exc
        checks["live_probe"] = "telegram_getme"
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise ValueError("Telegram rejected the bot token")
        bot = payload.get("result") or {}
        checks["bot_username"] = str(bot.get("username") or "")
    if not checks["adapter_available"]:
        raise ValueError(availability.get("error") or "channel adapter is unavailable")
    return {"status": "ok", "channel": channel, "checks": checks}


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

    # --- Routes ---

    @app.get("/channels/status", dependencies=[Depends(require_auth)])
    async def channels_status():
        """Return IM channel runtime and adapter status."""
        runtime = _get_channel_runtime()
        return runtime.status()

    @app.get("/channels/config", dependencies=[Depends(require_auth)])
    async def channels_config():
        """Return per-channel config summaries with secrets redacted."""
        from src.channels.registry import inspect_channels

        payload = _read_agent_config_payload()
        channels_section = payload.get("channels")
        channels_section = channels_section if isinstance(channels_section, dict) else {}
        statuses = inspect_channels(channels_section)
        summaries = []
        for name, availability in statuses.items():
            section = channels_section.get(name)
            section = section if isinstance(section, dict) else {}
            summaries.append(_redacted_channel_summary(name, section, availability))
        summaries.sort(key=lambda item: (not item["configured"], not item["enabled"], item["channel"]))
        return {"status": "ok", "channels": summaries, "env_path": str(_agent_config_path())}

    @app.put("/channels/config", dependencies=[Depends(require_auth)])
    async def update_channels_config(update: ChannelConfigUpdateRequest):
        channel = update.channel.strip().lower()
        if not _CHANNEL_ID_RE.fullmatch(channel):
            raise HTTPException(status_code=400, detail="invalid channel id")
        try:
            payload = _read_agent_config_payload()
            _apply_channel_update(
                payload,
                channel=channel,
                enabled=update.enabled,
                token=update.token,
                allowlist=update.allowlist,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        section = payload.get("channels", {}).get(channel, {})
        section = section if isinstance(section, dict) else {}
        from src.channels.registry import inspect_channel

        return {
            "status": "ok",
            "channel": _redacted_channel_summary(channel, section, inspect_channel(channel).to_dict()),
            "needs_restart": True,
        }

    @app.post("/channels/config/test", dependencies=[Depends(require_auth)])
    async def test_channels_config(probe: ChannelConfigTestRequest):
        channel = probe.channel.strip().lower()
        if not _CHANNEL_ID_RE.fullmatch(channel):
            raise HTTPException(status_code=400, detail="invalid channel id")
        token = probe.token
        if not (token or "").strip():
            section = _read_agent_config_payload().get("channels", {}).get(channel, {})
            section = section if isinstance(section, dict) else {}
            token = next((str(section[key]) for key in _SECRET_KEYS if section.get(key)), None)
        try:
            return await _probe_channel(channel, token)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/channels/start", dependencies=[Depends(require_auth)])
    async def channels_start():
        """Start configured IM channel adapters."""
        runtime = await _start_channel_runtime()
        return {"status": "started", **runtime.status()}

    @app.post("/channels/stop", dependencies=[Depends(require_auth)])
    async def channels_stop():
        """Stop configured IM channel adapters."""
        runtime = _get_channel_runtime()
        await runtime.stop()
        return {"status": "stopped", **runtime.status()}

    @app.post("/channels/pairing/command", dependencies=[Depends(require_auth)])
    async def channels_pairing_command(payload: ChannelPairingCommandRequest):
        """Run a pairing command against the shared pairing store."""
        from src.channels.pairing import handle_pairing_command

        return {
            "channel": payload.channel,
            "reply": handle_pairing_command(payload.channel, payload.command),
        }
