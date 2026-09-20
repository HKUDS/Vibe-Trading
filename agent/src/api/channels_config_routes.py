"""IM channel configuration HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_channels_config_routes(app, ...)``.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel

from src.channels.registry import inspect_channels
from src.config.writer import AgentConfigWriteError, save_channel_config_section

_DINGTALK_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"


# ---------------------------------------------------------------------------
# Pydantic models (defined locally -- NO shared modules, per maintainer rule)
# ---------------------------------------------------------------------------


class ChannelFieldSpec(BaseModel):
    """One editable field of a channel's config section."""

    key: str
    type: str  # "string" | "boolean"
    secret: bool = False
    required: bool = False
    description: str = ""


class ChannelConfigSchemaEntry(BaseModel):
    """Field contract plus availability for one channel."""

    name: str
    display_name: str
    available: bool
    enabled: bool
    install_hint: str = ""
    fields: List[ChannelFieldSpec]


class ChannelsConfigSchemaResponse(BaseModel):
    """Per-channel field contracts for the settings UI."""

    channels: List[ChannelConfigSchemaEntry]


class ChannelsConfigResponse(BaseModel):
    """Current per-channel config values; secrets are masked."""

    channels: Dict[str, Dict[str, Any]]


class UpdateChannelConfigRequest(BaseModel):
    """Field-level merge patch for one channel section."""

    values: Dict[str, Any]


class ToggleChannelConfigRequest(BaseModel):
    """Explicit enable target; omitted means flip the stored value."""

    enabled: Optional[bool] = None


class ChannelConfigEntryResponse(BaseModel):
    """Result of a config write: masked values plus hot-apply status."""

    name: str
    enabled: bool
    config: Dict[str, Any]
    applied: bool
    status: Optional[Dict[str, Any]] = None


class ChannelTestResponse(BaseModel):
    """Credential probe result; ``ok=False`` carries an honest reason."""

    name: str
    ok: bool
    reason: str  # "ok" | "missing_credentials" | "invalid_credentials" | "network" | "error" | "unsupported"
    detail: str = ""


# ---------------------------------------------------------------------------
# Field contracts (one dict entry per fully-guided channel)
# ---------------------------------------------------------------------------


def _guided_fields(name: str) -> List[ChannelFieldSpec]:
    """Return the editable credential fields for fully-guided channels."""
    if name == "dingtalk":
        return [
            ChannelFieldSpec(
                key="client_id",
                type="string",
                required=True,
                description=(
                    "Client ID (AppKey) of the DingTalk enterprise internal app "
                    "with the robot capability enabled"
                ),
            ),
            ChannelFieldSpec(
                key="client_secret",
                type="string",
                secret=True,
                required=True,
                description="Client Secret (AppSecret) of the same DingTalk app",
            ),
        ]
    return []


def _fields_for(name: str) -> List[ChannelFieldSpec]:
    return [
        ChannelFieldSpec(
            key="enabled",
            type="boolean",
            description="Run this channel with the IM runtime",
        ),
        *_guided_fields(name),
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_config() -> Dict[str, Any]:
    from src.channels.config import load_channels_config

    return load_channels_config()


def _build_schema() -> ChannelsConfigSchemaResponse:
    config = _load_config()
    statuses = inspect_channels(config)
    entries: List[ChannelConfigSchemaEntry] = []
    for name in sorted(statuses):
        item = statuses[name]
        entries.append(
            ChannelConfigSchemaEntry(
                name=name,
                display_name=str(item.get("display_name") or name),
                available=bool(item.get("available")),
                enabled=bool(item.get("enabled")),
                install_hint=str(item.get("install_hint") or ""),
                fields=_fields_for(name),
            )
        )
    return ChannelsConfigSchemaResponse(channels=entries)


def _known_channel_names() -> set[str]:
    return {entry.name for entry in _build_schema().channels}


def _mask_secret(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    return "****" + value[-4:] if len(value) > 4 else "****"


def _masked_values(name: str, section: Dict[str, Any]) -> Dict[str, Any]:
    """Project a stored section onto its declared fields, masking secrets."""
    values: Dict[str, Any] = {}
    for spec in _fields_for(name):
        raw = section.get(spec.key)
        if spec.secret:
            values[spec.key] = _mask_secret(raw)
        elif spec.type == "boolean":
            values[spec.key] = raw if isinstance(raw, bool) else False
        else:
            values[spec.key] = raw if isinstance(raw, str) else ""
    return values


def _build_config_response() -> ChannelsConfigResponse:
    config = _load_config()
    channels: Dict[str, Dict[str, Any]] = {}
    for name in _known_channel_names():
        section = config.get(name)
        channels[name] = _masked_values(name, section if isinstance(section, dict) else {})
    return ChannelsConfigResponse(channels=channels)


def _validate_updates(name: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """Type-check *values* against the channel's declared field contract."""
    specs = {spec.key: spec for spec in _fields_for(name)}
    unknown = sorted(key for key in values if key not in specs)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown field(s) for channel {name!r}: {', '.join(unknown)}",
        )
    updates: Dict[str, Any] = {}
    for key, value in values.items():
        spec = specs[key]
        if spec.type == "boolean":
            if not isinstance(value, bool):
                raise HTTPException(
                    status_code=422,
                    detail=f"Field {key!r} must be a boolean",
                )
        elif not isinstance(value, str):
            raise HTTPException(
                status_code=422,
                detail=f"Field {key!r} must be a string",
            )
        updates[key] = value
    return updates


def _check_required_fields(name: str, merged: Dict[str, Any]) -> None:
    """Refuse enabling a guided channel with missing credential fields."""
    if merged.get("enabled") is not True:
        return
    missing = [
        spec.key
        for spec in _guided_fields(name)
        if spec.required and not str(merged.get(spec.key) or "").strip()
    ]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot enable {name!r}: missing {', '.join(missing)}",
        )


def _validate_adapter_construction(name: str, merged: Dict[str, Any]) -> None:
    """Dry-run the adapter's own config validation before anything is written."""
    if not _guided_fields(name):
        return
    from src.channels.bus.queue import MessageBus
    from src.channels.registry import load_channel_class

    try:
        cls = load_channel_class(name)
        cls(dict(merged), MessageBus())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {name} config: {exc}",
        ) from exc


def _persist_section(name: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return save_channel_config_section(name, updates)
    except AgentConfigWriteError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Unable to save channel config: {exc}",
        ) from exc


def _host_channel_runtime():
    """Return the already-built channel runtime, or None; never builds one."""
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    runtime = getattr(host, "_channel_runtime", None) if host is not None else None
    if runtime is None:
        from src.api import state as _state

        runtime = _state._channel_runtime
    return runtime


async def _apply_channel_config(name: str) -> Optional[Dict[str, Any]]:
    """Hot-apply one channel's persisted config to a live runtime, if any."""
    runtime = _host_channel_runtime()
    manager = getattr(runtime, "manager", None) if runtime is not None else None
    if manager is None:
        return None
    return await manager.reconfigure_channel(name)


def _resolve_secret_updates(
    name: str,
    updates: Dict[str, Any],
    section: Dict[str, Any],
) -> Dict[str, Any]:
    """Map a masked secret echo (``****…``) back to the stored value."""
    specs = {spec.key: spec for spec in _fields_for(name)}
    resolved: Dict[str, Any] = {}
    for key, value in updates.items():
        spec = specs[key]
        if spec.secret and isinstance(value, str) and value.startswith("****"):
            stored = section.get(key)
            resolved[key] = stored if isinstance(stored, str) else ""
        else:
            resolved[key] = value
    return resolved


async def _probe_dingtalk_credentials(
    client_id: str,
    client_secret: str,
) -> tuple[bool, str, str]:
    """Exchange app credentials for an access token (DingTalk credential check)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(
                _DINGTALK_TOKEN_URL,
                json={"appKey": client_id, "appSecret": client_secret},
            )
    except httpx.HTTPError as exc:
        return False, "network", f"{type(exc).__name__}: {exc}"

    snippet = resp.text[:200]
    if resp.status_code == 200:
        try:
            body = resp.json()
        except ValueError:
            return False, "error", f"HTTP 200 with non-JSON body: {snippet}"
        if isinstance(body, dict) and body.get("accessToken"):
            return True, "ok", ""
        return False, "invalid_credentials", snippet
    if 400 <= resp.status_code < 500:
        return False, "invalid_credentials", f"HTTP {resp.status_code}: {snippet}"
    return False, "error", f"HTTP {resp.status_code}: {snippet}"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_channels_config_routes(
    app: FastAPI,
    require_local_or_auth: AuthDep | None = None,
    require_settings_write_auth: AuthDep | None = None,
) -> None:
    """Mount the channel configuration routes onto ``app``."""
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")

    if host is None:
        raise RuntimeError(
            "register_channels_config_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    if require_local_or_auth is None:
        require_local_or_auth = host.require_local_or_auth
    if require_settings_write_auth is None:
        require_settings_write_auth = host.require_settings_write_auth

    # --- Routes ---

    @app.get(
        "/channels/config-schema",
        response_model=ChannelsConfigSchemaResponse,
        dependencies=[Depends(require_local_or_auth)],
    )
    async def channels_config_schema():
        """Return per-channel field contracts for the settings UI."""
        return _build_schema()

    @app.get(
        "/channels/config",
        response_model=ChannelsConfigResponse,
        dependencies=[Depends(require_local_or_auth)],
    )
    async def channels_config():
        """Return current channel config values with secrets masked."""
        return _build_config_response()

    @app.put(
        "/channels/config/{name}",
        response_model=ChannelConfigEntryResponse,
        dependencies=[Depends(require_settings_write_auth)],
    )
    async def update_channel_config(name: str, payload: UpdateChannelConfigRequest):
        """Merge-patch one channel section, persist it, and hot-apply it."""
        if name not in _known_channel_names():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown channel: {name!r}",
            )
        updates = _validate_updates(name, payload.values)

        stored = _load_config().get(name)
        section = stored if isinstance(stored, dict) else {}
        updates = _resolve_secret_updates(name, updates, section)
        merged = {**section, **updates}
        _check_required_fields(name, merged)
        _validate_adapter_construction(name, merged)

        saved = _persist_section(name, updates)
        status_entry = await _apply_channel_config(name)
        return ChannelConfigEntryResponse(
            name=name,
            enabled=saved.get("enabled") is True,
            config=_masked_values(name, saved),
            applied=status_entry is not None,
            status=status_entry,
        )

    @app.post(
        "/channels/config/{name}/test",
        response_model=ChannelTestResponse,
        dependencies=[Depends(require_settings_write_auth)],
    )
    async def test_channel_config(name: str):
        """Probe the stored credentials of one channel without changing anything."""
        if name not in _known_channel_names():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown channel: {name!r}",
            )
        if name != "dingtalk":
            return ChannelTestResponse(
                name=name,
                ok=False,
                reason="unsupported",
                detail="Connection test is only implemented for DingTalk so far",
            )

        stored = _load_config().get(name)
        section = stored if isinstance(stored, dict) else {}
        client_id = str(section.get("client_id") or "").strip()
        client_secret = str(section.get("client_secret") or "").strip()
        if not client_id or not client_secret:
            return ChannelTestResponse(
                name=name,
                ok=False,
                reason="missing_credentials",
                detail="Save client_id and client_secret first",
            )

        ok, reason, detail = await _probe_dingtalk_credentials(client_id, client_secret)
        return ChannelTestResponse(name=name, ok=ok, reason=reason, detail=detail)

    @app.post(
        "/channels/config/{name}/toggle",
        response_model=ChannelConfigEntryResponse,
        dependencies=[Depends(require_settings_write_auth)],
    )
    async def toggle_channel_config(name: str, payload: Optional[ToggleChannelConfigRequest] = None):
        """Flip a channel's enabled flag without touching its credentials."""
        if name not in _known_channel_names():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown channel: {name!r}",
            )

        stored = _load_config().get(name)
        section = stored if isinstance(stored, dict) else {}
        current = section.get("enabled") is True
        target = payload.enabled if payload is not None and payload.enabled is not None else not current

        merged = {**section, "enabled": target}
        _check_required_fields(name, merged)

        saved = _persist_section(name, {"enabled": target})
        status_entry = await _apply_channel_config(name)
        return ChannelConfigEntryResponse(
            name=name,
            enabled=saved.get("enabled") is True,
            config=_masked_values(name, saved),
            applied=status_entry is not None,
            status=status_entry,
        )
