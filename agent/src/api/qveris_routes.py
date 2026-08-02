"""QVeris settings and status routes."""

from __future__ import annotations

import sys as _sys
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from src.tools.qveris_tool import (
    INVITE_CODE,
    SIGNUP_URL,
    DEFAULT_BASE_URL,
    QVerisClient,
    QVerisConfig,
    _read_config_file,
    has_qveris_credentials,
    is_qveris_configured,
    load_qveris_config,
    mask_api_key,
    normalize_qveris_mode,
    save_qveris_config,
)

qveris_router = APIRouter()
_security = HTTPBearer(auto_error=False)


class QVerisConfigResponse(BaseModel):
    """Redacted QVeris config response."""

    enabled: bool
    base_url: str
    api_key_masked: str
    mode: Literal["free", "paid"]
    budget_credits_per_session: float
    configured: bool
    signup_url: str
    invite_code: str


class QVerisConfigUpdate(BaseModel):
    """QVeris config update payload."""

    enabled: bool | None = None
    base_url: str | None = None
    api_key: str | None = None
    mode: Literal["free", "paid"] | None = None
    budget_credits_per_session: float | None = Field(default=None, ge=0)


class QVerisStatusResponse(BaseModel):
    """QVeris runtime status response."""

    enabled: bool
    ok: bool
    error: str | None
    remaining_credits: float | None
    recent: list[dict[str, Any]]
    signup_url: str
    invite_code: str


def _host():
    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    if host is None:
        raise RuntimeError("api_server module is not loaded")
    return host


async def _require_auth(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Security(_security),
) -> None:
    """Delegate read auth to api_server.require_auth."""
    await _host().require_auth(request, cred)


async def _require_settings_write_auth(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Security(_security),
) -> None:
    """Delegate write auth to api_server.require_settings_write_auth."""
    await _host().require_settings_write_auth(request, cred)


def _config_response(config: QVerisConfig) -> QVerisConfigResponse:
    return QVerisConfigResponse(
        enabled=config.enabled,
        base_url=config.base_url,
        api_key_masked=mask_api_key(config.api_key),
        mode=normalize_qveris_mode(config.mode),  # type: ignore[arg-type]
        budget_credits_per_session=float(config.budget_credits_per_session),
        configured=has_qveris_credentials(config),
        signup_url=SIGNUP_URL,
        invite_code=INVITE_CODE,
    )


def _validate_base_url(base_url: str) -> str:
    value = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="base_url must be http(s)")
    return value


def _events_from_usage(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, dict):
        events = data.get("events") or data.get("items") or data.get("data")
    elif isinstance(data, list):
        events = data
    else:
        events = payload.get("events") or payload.get("items") or []
    if not isinstance(events, list):
        return []
    recent: list[dict[str, Any]] = []
    for event in events[:10]:
        if not isinstance(event, dict):
            continue
        recent.append(
            {
                "ts": str(event.get("ts") or event.get("created_at") or event.get("timestamp") or ""),
                "tool_id": str(event.get("tool_id") or ""),
                "cost": float(event.get("cost") or event.get("amount_credits") or 0.0),
                "charge_outcome": str(event.get("charge_outcome") or ""),
            }
        )
    return recent


@qveris_router.get(
    "/qveris/config",
    response_model=QVerisConfigResponse,
    dependencies=[Depends(_require_auth)],
)
async def get_qveris_config() -> QVerisConfigResponse:
    """Return redacted QVeris config."""
    return _config_response(load_qveris_config())


@qveris_router.put(
    "/qveris/config",
    response_model=QVerisConfigResponse,
    dependencies=[Depends(_require_settings_write_auth)],
)
async def put_qveris_config(update: QVerisConfigUpdate) -> QVerisConfigResponse:
    """Persist QVeris config changes."""
    existing = _read_config_file()
    cfg = QVerisConfig(
        enabled=existing.enabled,
        base_url=existing.base_url,
        api_key=existing.api_key,
        mode=existing.mode,
        budget_credits_per_session=existing.budget_credits_per_session,
    )
    if update.base_url is not None:
        cfg.base_url = _validate_base_url(update.base_url)
    if update.api_key:
        cfg.api_key = update.api_key.strip()
    if update.mode is not None:
        cfg.mode = normalize_qveris_mode(update.mode)
        cfg.enabled = cfg.mode == "paid"
    elif update.enabled is not None:
        cfg.enabled = bool(update.enabled)
        cfg.mode = "paid" if cfg.enabled else "free"
    if update.budget_credits_per_session is not None:
        cfg.budget_credits_per_session = float(update.budget_credits_per_session)
    save_qveris_config(cfg)
    return _config_response(load_qveris_config())


@qveris_router.get(
    "/qveris/status",
    response_model=QVerisStatusResponse,
    dependencies=[Depends(_require_auth)],
)
async def get_qveris_status() -> QVerisStatusResponse:
    """Return QVeris availability, credits, and recent usage."""
    cfg = load_qveris_config()
    if not has_qveris_credentials(cfg):
        return QVerisStatusResponse(
            enabled=cfg.enabled,
            ok=False,
            error="QVeris is not configured",
            remaining_credits=None,
            recent=[],
            signup_url=SIGNUP_URL,
            invite_code=INVITE_CODE,
        )
    if not is_qveris_configured(cfg):
        return QVerisStatusResponse(
            enabled=cfg.enabled,
            ok=False,
            error="QVeris paid mode is off; free public data routing is active.",
            remaining_credits=None,
            recent=[],
            signup_url=SIGNUP_URL,
            invite_code=INVITE_CODE,
        )
    try:
        client = QVerisClient(cfg)
        search = client.search("status", limit=1)
        usage = client.usage_history(limit=10, page_size=10)
        remaining = search.get("remaining_credits")
        return QVerisStatusResponse(
            enabled=cfg.enabled,
            ok=True,
            error=None,
            remaining_credits=float(remaining) if remaining is not None else None,
            recent=_events_from_usage(usage),
            signup_url=SIGNUP_URL,
            invite_code=INVITE_CODE,
        )
    except Exception as exc:  # noqa: BLE001 - status endpoint reports health.
        return QVerisStatusResponse(
            enabled=cfg.enabled,
            ok=False,
            error=str(exc),
            remaining_credits=None,
            recent=[],
            signup_url=SIGNUP_URL,
            invite_code=INVITE_CODE,
        )
