"""IM channel configuration HTTP routes (web config forms + hot update).

Mounted by ``agent/api_server.py`` via ``register_channels_config_routes(app, ...)``.
Composes the delivered building blocks — the atomic writer
(:func:`src.config.writer.update_channel_section`), the connection-test hook
(:meth:`src.channels.base.BaseChannel.test_connection`), per-channel hot reload
(:meth:`src.channels.manager.ChannelManager.reload_channel` +
:func:`src.api.state.reset_channel_runtime`) and field metadata
(:mod:`src.channels.config_meta`) — without reimplementing any of them.

Security properties owned here: secret values never cross the wire (masked via
``split_values_secrets``), and a section that fails validation or the
enable-transition credential probe is rejected with 422 *before* anything is
written to disk.

Plugin channels discovered via entry points are intentionally not surfaced
here; they remain file-configured.
"""

from __future__ import annotations

import asyncio
import logging
import sys as _sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.api import state as _state
from src.channels import config as _channels_config
from src.channels.bus.queue import MessageBus
from src.channels.config_meta import SECRET_KEY_RE, channel_field_hints, split_values_secrets
from src.channels.registry import (
    discover_channel_names,
    inspect_channel,
    inspect_channels,
    load_channel_class,
)
from src.config import writer as _config_writer
from src.config.paths import get_config_path

logger = logging.getLogger(__name__)

_PROBE_CODES = frozenset({"ok", "invalid_credentials", "network", "unsupported"})
_VERIFY_BLOCK_CODES = frozenset({"invalid_credentials", "network"})

# Bound the fallback stop so a wedged adapter cannot stall the reset + restart.
_FALLBACK_STOP_TIMEOUT_S = 10.0

# Per-channel lifecycle keys the manager consumes from the section; they are
# not adapter model fields but are legitimate config content (#341 lineage).
_MANAGER_OVERRIDE_KEYS = frozenset(
    {
        "send_progress",
        "send_tool_hints",
        "show_reasoning",
        "sendProgress",
        "sendToolHints",
        "showReasoning",
    }
)

# Per-channel PUT/test serialization + one lock around runtime reset/rebuild.
_channel_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_runtime_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Pydantic models (defined locally -- NO shared modules, per maintainer rule)
# ---------------------------------------------------------------------------


class ChannelConfigUpdateRequest(BaseModel):
    """Merge-patch body for one channel section.

    ``clear_<field>: true`` flags arrive as extra keys and remove the stored
    key (used for secrets the form never echoes back).
    """

    model_config = ConfigDict(extra="allow")

    config: dict[str, Any] = Field(default_factory=dict)
    skip_verify: bool = False


class ChannelTestRequest(BaseModel):
    """Optional unsaved partial config for an ephemeral connection test.

    ``clear_<field>: true`` flags arrive as extra keys, matching the PUT body.
    """

    model_config = ConfigDict(extra="allow")

    config: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Helpers (host state resolved via sys.modules, late-access for monkeypatch)
# ---------------------------------------------------------------------------


def _host():
    """Return the ``api_server`` host module for late-access attribute reads."""
    return _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")


def _known_channel_names() -> set[str]:
    """Return the discovered built-in channel adapter names."""
    return set(discover_channel_names())


def _is_secret_key(name: str, key: str) -> bool:
    """Return whether a config key must never cross the wire in clear."""
    if SECRET_KEY_RE.search(key):
        return True
    return any(hint["key"] == key and hint["secret"] for hint in channel_field_hints(name))


def _stored_section(name: str) -> dict[str, Any]:
    """Return the channel's current on-disk config section."""
    section = _channels_config.load_channels_config().get(name)
    return dict(section) if isinstance(section, dict) else {}


def _effective_section(name: str, section: dict[str, Any]) -> dict[str, Any]:
    """Return the stored section backfilled with adapter defaults.

    A never-configured channel has no on-disk section; without defaults the
    generic form seeds empty strings and typed fields (``int``, ``Literal``)
    reject the untouched form on Test/Save. Secret masking is unaffected:
    defaults are empty, so ``secrets`` still reflects only the stored state.
    """
    try:
        defaults = load_channel_class(name).default_config()
    except Exception:  # noqa: BLE001 - an unloadable adapter keeps the raw section
        logger.debug("Config defaults unavailable for channel '%s'", name, exc_info=True)
        return section
    if not isinstance(defaults, dict):
        return section
    return {**defaults, **section}


def _unknown_keys(cls: type, patch: dict[str, Any]) -> list[str]:
    """Return patch keys that are neither adapter fields nor manager overrides.

    Shared by PUT and POST /test so both reject an unrecognized key with the
    same 422 instead of one writing-refusing and one silently dropping it
    into the probe instance (pydantic ``extra="ignore"``).
    """
    allowed = set(cls.default_config()) | _MANAGER_OVERRIDE_KEYS
    return sorted(key for key in patch if key not in allowed)


def _patch_of(name: str, body: dict[str, Any]) -> dict[str, Any]:
    """Filter a body patch: an empty string on a secret key keeps the stored value."""
    return {
        key: value
        for key, value in body.items()
        if not (_is_secret_key(name, key) and isinstance(value, str) and not value.strip())
    }


def _clear_flags(extra: dict[str, Any] | None) -> list[str]:
    """Return the ``clear_<field>`` targets from a request's extra keys."""
    return [
        key[len("clear_") :]
        for key, value in (extra or {}).items()
        if key.startswith("clear_") and len(key) > len("clear_") and value
    ]


def _supports_connection_test(name: str) -> bool:
    """Return whether the adapter class declares a standalone connection test."""
    try:
        return bool(load_channel_class(name).supports_connection_test)
    except Exception:  # noqa: BLE001 - an unloadable adapter has no test support
        return False


def _live_status(name: str) -> dict[str, Any]:
    """Return the running manager's status entry for *name* ({} if no runtime)."""
    runtime = getattr(_host(), "_channel_runtime", None)
    if runtime is None:
        return {}
    live = (runtime.status().get("channels") or {}).get(name)
    return dict(live) if isinstance(live, dict) else {}


def _channel_entry(name: str, section: dict[str, Any], status_map: dict[str, Any]) -> dict[str, Any]:
    """Build one channel's GET-shape entry; secrets are masked, never returned."""
    values, secrets = split_values_secrets(name, _effective_section(name, section))
    available = bool(status_map.get("available", False))
    return {
        "display_name": str(status_map.get("display_name") or name),
        "available": available,
        "loaded": bool(status_map.get("loaded", False)),
        "install_hint": str(status_map.get("install_hint") or ""),
        "error": str(status_map.get("error") or ""),
        "supports_test": _supports_connection_test(name),
        "sdk_available": bool(status_map.get("sdk_available", available)),
        "fields": channel_field_hints(name),
        "values": values,
        "secrets": secrets,
    }


def _fresh_entry(name: str) -> dict[str, Any]:
    """Build a channel entry from the current disk section + merged status."""
    status_map = inspect_channel(name).to_dict()
    status_map.update(_live_status(name))
    return _channel_entry(name, _stored_section(name), status_map)


def _display_config_path(path: Path) -> str:
    """Return a display-only config path: home-relative when possible.

    The absolute path discloses the local username and directory layout to any
    read-authorized caller; the UI only needs to show the operator which file
    to edit by hand.
    """
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return path.name


def _scrub_detail(name: str, text: Any, section: dict[str, Any]) -> str:
    """Mask every secret value of *section* found in *text* (defense in depth)."""
    cleaned = str(text or "")
    for key, value in section.items():
        if _is_secret_key(name, key) and isinstance(value, str) and value:
            cleaned = cleaned.replace(value, "***")
    return cleaned


def _validation_fields(exc: ValidationError) -> list[str]:
    """Return error field locations from a ValidationError (never values)."""
    fields: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", ()))
        fields.append(loc or str(error.get("type", "invalid")))
    return fields


def _reject_validation(fields: list[str]) -> HTTPException:
    """Build the frozen 422 ``validation_error`` envelope."""
    return HTTPException(
        status_code=422,  # literal per repo convention (the starlette constant is deprecated)
        detail={
            "code": "validation_error",
            "fields": fields,
            "message": "invalid fields: " + ", ".join(fields),
        },
    )


def _build_ephemeral(name: str, section: dict[str, Any]) -> tuple[type, Any]:
    """Construct a throwaway adapter instance to validate *section*.

    Mirrors ``ChannelManager._build_channel`` construction. Raises the frozen
    422 ``validation_error`` envelope when the section cannot build; error
    values (which may echo secrets) never leave this function.
    """
    try:
        cls = load_channel_class(name)
    except Exception as exc:  # noqa: BLE001 - an unloadable adapter cannot validate
        raise _reject_validation([type(exc).__name__]) from None
    try:
        return cls, cls(section, MessageBus())
    except ValidationError as exc:
        raise _reject_validation(_validation_fields(exc)) from None
    except Exception as exc:  # noqa: BLE001 - any construction error is a config error
        raise _reject_validation([type(exc).__name__]) from None


async def _hot_apply(name: str, section: dict[str, Any] | None) -> str:
    """Apply a written section to the cached runtime; return the apply mode.

    Running runtime → per-channel hot swap; built-but-stopped → drop the stale
    singleton so the next explicit Start reads fresh config; never built →
    no-op (the lazy build reads disk). A failed swap falls back to a full
    reset + restart through the same path ``/channels/start`` uses.
    """
    host = _host()
    runtime = getattr(host, "_channel_runtime", None)
    if runtime is None:
        return "deferred"
    if not runtime.status().get("running"):
        async with _runtime_lock:
            _state.reset_channel_runtime()
        return "reset"
    try:
        await runtime.manager.reload_channel(name, section)
        return "hot_swapped"
    except Exception:  # noqa: BLE001 - a failed swap must not strand the runtime
        logger.warning(
            "Hot reload failed for channel %s; falling back to a runtime reset",
            name,
            exc_info=True,
        )
        async with _runtime_lock:
            try:
                await asyncio.wait_for(runtime.stop(), timeout=_FALLBACK_STOP_TIMEOUT_S)
            except Exception:  # noqa: BLE001 - a wedged stop must not block the rebuild
                logger.warning(
                    "Stopping the failed runtime timed out; resetting anyway",
                    exc_info=True,
                )
            _state.reset_channel_runtime()
            await host._get_channel_runtime().start(start_manager=True)
        return "reset"


async def _apply_update(name: str, payload: ChannelConfigUpdateRequest) -> dict[str, Any]:
    """Validate → optional enable-transition probe → write → hot apply."""
    stored = _stored_section(name)
    patch = _patch_of(name, payload.config)
    clears = _clear_flags(payload.model_extra)
    merged = {**stored, **patch}
    for key in clears:
        merged.pop(key, None)

    cls, instance = _build_ephemeral(name, merged)

    unknown = _unknown_keys(cls, patch)
    if unknown:
        raise _reject_validation(unknown)

    enabling = bool(merged.get("enabled")) and not bool(stored.get("enabled"))
    if enabling and cls.supports_connection_test and not payload.skip_verify:
        try:
            probe = await instance.test_connection()
        except Exception as exc:  # noqa: BLE001 - a raising probe is a network-class failure
            probe = {
                "ok": False,
                "code": "network",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        if not probe.get("ok"):
            code = probe.get("code")
            message = _scrub_detail(name, probe.get("detail", ""), merged)[:200]
            raise HTTPException(
                status_code=422,
                detail={
                    "code": code if code in _VERIFY_BLOCK_CODES else "network",
                    "fields": [],
                    "message": message or "connection probe failed",
                },
            )

    try:
        _config_writer.update_channel_section(name, patch, clears=clears)
    except _config_writer.ConfigNotWritableError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "config_not_writable"},
        ) from None

    fresh = _stored_section(name)
    applied = await _hot_apply(name, fresh or None)
    return {"channel": _fresh_entry(name), "applied": applied}


async def _run_test(name: str, body: dict[str, Any] | None, clears: list[str]) -> dict[str, Any]:
    """Probe credentials on an ephemeral instance; never persists anything."""
    stored = _stored_section(name)
    patch = _patch_of(name, body or {})
    merged = {**stored, **patch}
    for key in clears:
        merged.pop(key, None)
    tested_saved_config = not body
    sdk_fallback = bool(inspect_channel(name).to_dict().get("available", False))

    def _result(ok: bool, code: str, detail: str, sdk_available: bool) -> dict[str, Any]:
        return {
            "ok": ok,
            "code": code,
            "detail": _scrub_detail(name, detail, merged),
            "sdk_available": sdk_available,
            "tested_saved_config": tested_saved_config,
        }

    try:
        cls = load_channel_class(name)
    except Exception:  # noqa: BLE001 - an unloadable adapter cannot be probed
        cls = None
    if cls is None or not getattr(cls, "supports_connection_test", False):
        # Nothing network-facing is constructed for an unsupported channel.
        return _result(False, "unsupported", "", sdk_fallback)

    unknown = _unknown_keys(cls, patch)
    if unknown:
        raise _reject_validation(unknown)

    try:
        instance = cls(merged, MessageBus())
    except ValidationError as exc:
        detail = "validation_error: " + ", ".join(_validation_fields(exc))
        return _result(False, "invalid_credentials", detail, sdk_fallback)
    except Exception as exc:  # noqa: BLE001 - a broken section cannot be probed
        return _result(False, "invalid_credentials", f"validation_error: {type(exc).__name__}", sdk_fallback)

    probe = await instance.test_connection()
    code = probe.get("code")
    sdk_available = probe.get("sdk_available")
    return _result(
        bool(probe.get("ok")),
        code if code in _PROBE_CODES else "network",
        probe.get("detail", ""),
        bool(sdk_available) if sdk_available is not None else sdk_fallback,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_channels_config_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
    require_settings_write_auth: AuthDep | None = None,
) -> None:
    """Mount the channel-config routes onto ``app``.

    Resolves the auth dependencies from the host ``api_server`` module via
    ``sys.modules`` when not passed explicitly (same idiom as
    ``channels_routes`` / ``settings_routes``).
    """
    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")

    if host is None:
        raise RuntimeError(
            "register_channels_config_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    if require_auth is None:
        require_auth = host.require_auth
    if require_settings_write_auth is None:
        require_settings_write_auth = host.require_settings_write_auth

    @app.get("/channels/config", dependencies=[Depends(require_auth)])
    async def get_channels_config():
        """Return every channel's config form data with masked secrets."""
        availability = inspect_channels()
        disk = _channels_config.load_channels_config()
        runtime = getattr(host, "_channel_runtime", None)
        running = False
        live: dict[str, Any] = {}
        if runtime is not None:
            snapshot = runtime.status()
            running = bool(snapshot.get("running"))
            live = snapshot.get("channels") or {}

        path = get_config_path()
        channels: dict[str, Any] = {}
        for name in sorted(availability):
            section = disk.get(name)
            status_map = dict(availability[name])
            live_entry = live.get(name)
            if isinstance(live_entry, dict):
                status_map.update(live_entry)
            channels[name] = _channel_entry(
                name, section if isinstance(section, dict) else {}, status_map
            )
        return {
            "config_path": _display_config_path(path),
            "writable": path.suffix.lower() == ".json",
            "runtime_running": running,
            "channels": channels,
        }

    @app.put(
        "/channels/config/{name}",
        dependencies=[Depends(require_settings_write_auth)],
    )
    async def put_channel_config(name: str, payload: ChannelConfigUpdateRequest):
        """Merge-patch one channel section with pre-write validation + hot apply."""
        if name not in _known_channel_names():
            raise HTTPException(status_code=404, detail=f"Unknown channel: {name}")
        async with _channel_locks[name]:
            return await _apply_update(name, payload)

    @app.post(
        "/channels/{name}/test",
        dependencies=[Depends(require_settings_write_auth)],
    )
    async def post_channel_test(name: str, payload: ChannelTestRequest):
        """Probe credentials ephemerally; never writes to the config file."""
        if name not in _known_channel_names():
            raise HTTPException(status_code=404, detail=f"Unknown channel: {name}")
        async with _channel_locks[name]:
            return await _run_test(name, payload.config, _clear_flags(payload.model_extra))
