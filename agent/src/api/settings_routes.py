"""LLM and data-source settings HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_settings_routes(app, ...)``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys as _sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from src.config.accessor import reset_env_config
from src.config.gildata_features import FEATURES_ENV, GildataFeature, selected_features
from src.providers.settings import SettingsStore

logger = logging.getLogger(__name__)

# Agent root (agent/) — resolved from this file's location (agent/src/api/).
_AGENT_DIR = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# HTTP request/response models; provider metadata and discovery are shared
# ---------------------------------------------------------------------------


# "none" is an explicit value direct OpenAI needs to allow function tools on
# gpt-5.6-* models; a provider with its own levels lists them in llm_providers.json.
from src.providers.discovery import (
    LLMModelsResponse as LLMModelsResponse,
)
from src.providers.discovery import (
    LLMProviderOption as LLMProviderOption,
)
from src.providers.discovery import (
    _extract_model_ids as _extract_model_ids,
)
from src.providers.discovery import (
    _list_claude_cli_models,
    _list_openai_codex_models,
    _list_provider_models,
    _validate_model_base_url,
)
from src.providers.registry import CATALOG_PATH, provider_catalog


class LLMSettingsResponse(BaseModel):
    """Current LLM runtime settings."""

    provider: str
    model_name: str
    base_url: str
    api_key_env: Optional[str] = None
    api_key_configured: bool
    api_key_hint: Optional[str] = None
    api_key_required: bool
    temperature: float
    timeout_seconds: int
    max_retries: int
    reasoning_effort: str
    sse_timeout_seconds: int
    env_path: str
    providers: List[LLMProviderOption]


class UpdateLLMSettingsRequest(BaseModel):
    """Update LLM settings persisted to agent/.env."""

    provider: str = Field(..., min_length=1)
    model_name: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    clear_api_key: bool = False
    temperature: float = 0.0
    timeout_seconds: int = Field(120, ge=1, le=3600)
    max_retries: int = Field(2, ge=0, le=20)
    reasoning_effort: Optional[str] = None


class ListLLMModelsRequest(BaseModel):
    """Resolve live model choices without persisting credentials or settings."""

    provider: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    refresh: bool = False


class SourceOrderEntry(BaseModel):
    """One market's fallback-chain order (default + override state)."""

    market: str
    env_var: str
    default_order: List[str]
    effective_order: List[str]
    override: Optional[List[str]] = None
    override_invalid: bool = False


class SourceOrderUpdate(BaseModel):
    """Reorder one market's fallback chain (null/empty order = reset)."""

    market: str
    order: Optional[List[str]] = None


class DataSourceSettingsResponse(BaseModel):
    """Current data source credential settings."""

    tushare_token_configured: bool
    tushare_token_hint: Optional[str] = None
    gildata_features: list[GildataFeature] = Field(default_factory=list)
    gildata_token_configured: bool
    gildata_token_hint: Optional[str] = None
    baostock_supported: bool
    baostock_installed: bool
    baostock_message: str
    env_path: str
    source_orders: List[SourceOrderEntry] = Field(default_factory=list)


class UpdateDataSourceSettingsRequest(BaseModel):
    """Update project-local data source credentials."""

    tushare_token: Optional[str] = None
    clear_tushare_token: bool = False
    gildata_token: Optional[str] = None
    gildata_features: list[GildataFeature] | None = None
    clear_gildata_token: bool = False
    source_orders: Optional[List[SourceOrderUpdate]] = None


# ---------------------------------------------------------------------------
# Provider metadata (settings-exclusive)
# ---------------------------------------------------------------------------

LLM_PROVIDER_CONFIG_PATH = CATALOG_PATH


def _load_llm_providers() -> List[LLMProviderOption]:
    """Expose the same catalog used by the in-process gateway and CLI."""
    return [LLMProviderOption(**item) for item in provider_catalog()]


LLM_PROVIDERS = _load_llm_providers()
LLM_PROVIDER_BY_NAME = {provider.name: provider for provider in LLM_PROVIDERS}
LLM_API_KEY_PLACEHOLDERS = {"", "sk-or-v1-your-key-here", "sk-xxx", "xxx", "gsk_xxx"}
TUSHARE_TOKEN_PLACEHOLDERS = {"", "your-tushare-token"}
GILDATA_TOKEN_PLACEHOLDERS = {"", "your-gildata-token"}


# ---------------------------------------------------------------------------
# Host access helpers (late-binding for test monkeypatch compat)
# ---------------------------------------------------------------------------


def _host():
    """Return the ``api_server`` module for late-access attribute reads.

    Tests monkeypatch ``ENV_PATH``, ``ENV_EXAMPLE_PATH``, ``_baostock_supported``
    and ``_baostock_installed`` directly on the ``api_server`` module; every
    function that reads these symbols goes through ``_host()`` so monkeypatched
    values take effect.
    """
    return _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")


# ---------------------------------------------------------------------------
# Settings-exclusive helpers
# ---------------------------------------------------------------------------


def _baostock_supported() -> bool:
    """Check whether the project has a BaoStock loader implementation."""
    host = _host()
    agent_dir = host.AGENT_DIR if host is not None else _AGENT_DIR
    loader_dir = agent_dir / "backtest" / "loaders"
    return any((loader_dir / name).exists() for name in ("baostock.py", "baostock_loader.py"))


def _baostock_installed() -> bool:
    """Check whether the optional BaoStock package is importable."""
    return importlib.util.find_spec("baostock") is not None


def _settings_store() -> SettingsStore:
    host = _host()
    return SettingsStore(host.ENV_PATH, getattr(host, "LEGACY_ENV_PATH", _AGENT_DIR / ".env"), host.ENV_EXAMPLE_PATH)


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _build_llm_settings_response(
    values: Optional[Dict[str, str]] = None,
) -> LLMSettingsResponse:
    """Build the public settings payload from dotenv values."""
    host = _host()
    env_values = values if values is not None else _settings_store().read()
    provider_name = env_values.get("LANGCHAIN_PROVIDER", "openai").strip().lower()
    provider = LLM_PROVIDER_BY_NAME.get(provider_name, LLM_PROVIDER_BY_NAME["openai"])
    api_key = env_values.get(provider.api_key_env or "", "") if provider.api_key_env else ""
    api_key_configured = host._is_configured_secret(api_key, LLM_API_KEY_PLACEHOLDERS)
    api_key_hint = None
    if provider.auth_type == "oauth":
        try:
            from src.providers.openai_codex import get_openai_codex_login_status

            token = get_openai_codex_login_status()
        except Exception:
            token = None
        api_key_configured = bool(token)
        api_key_hint = None
    elif provider.auth_type == "gh_cli":
        try:
            from src.providers.copilot_auth import get_copilot_auth_status

            authenticated, auth_status = get_copilot_auth_status()
        except Exception:
            authenticated, auth_status = False, ""
        api_key_configured = authenticated
        api_key_hint = auth_status if authenticated else None
    elif provider.auth_type == "claude_cli":
        try:
            from src.providers.claude_cli import get_claude_cli_auth_status

            authenticated, auth_status = get_claude_cli_auth_status()
        except Exception:
            authenticated, auth_status = False, ""
        api_key_configured = authenticated
        api_key_hint = auth_status if authenticated else None
    options = LLM_PROVIDERS
    if provider_name == "custom":
        from src.providers.custom_profiles import CustomProviderStore

        active = next((p for p in CustomProviderStore().list_public() if p["active"]), None)
        active_model = active["model"] if active else env_values.get("LANGCHAIN_MODEL_NAME", "")
        active_url = active["base_url"] if active else ""
        provider = LLMProviderOption(name="custom", label="Custom (credential vault)",
            api_key_env=None, base_url_env="OPENAI_BASE_URL", default_model=active_model,
            default_base_url=active_url, auth_type="credential_vault", reasoning_efforts=[])
        env_values = {**env_values, "LANGCHAIN_MODEL_NAME": active_model, "OPENAI_BASE_URL": active_url}
        api_key_configured, api_key_hint = bool(active and active["api_key_configured"]), None
        options = [*LLM_PROVIDERS, provider]
    return LLMSettingsResponse(
        provider=provider.name,
        model_name=env_values.get("LANGCHAIN_MODEL_NAME", provider.default_model),
        base_url=env_values.get(provider.base_url_env, provider.default_base_url),
        api_key_env=provider.api_key_env,
        api_key_configured=api_key_configured,
        api_key_hint=api_key_hint,
        api_key_required=provider.api_key_required,
        temperature=host._coerce_float(env_values.get("LANGCHAIN_TEMPERATURE", "0.0"), 0.0),
        timeout_seconds=host._coerce_int(env_values.get("TIMEOUT_SECONDS", "120"), 120),
        max_retries=host._coerce_int(env_values.get("MAX_RETRIES", "2"), 2),
        reasoning_effort=env_values.get("LANGCHAIN_REASONING_EFFORT", "").strip().lower(),
        sse_timeout_seconds=host._coerce_int(env_values.get("VIBE_TRADING_SSE_TIMEOUT", "90"), 90),
        env_path=host._project_relative_path(host.ENV_PATH),
        providers=options,
    )




def _build_source_orders(env_values: Dict[str, str]) -> List[SourceOrderEntry]:
    """Build per-market source-order entries for the settings payload.

    ``effective_order`` reflects the running process (registry state after a
    refresh); ``override`` reflects the persisted dotenv value, with
    ``override_invalid`` flagging values that failed validation (kept in the
    file for transparency, but not applied).
    """
    from backtest.loaders import registry

    registry.refresh_source_order_overrides()
    entries: List[SourceOrderEntry] = []
    for market in sorted(registry._DEFAULT_CHAINS):
        env_var = registry.source_order_env_var(market)
        default_order = registry.get_default_source_order(market)
        parsed = registry.parse_source_order(env_values.get(env_var, ""))
        entries.append(
            SourceOrderEntry(
                market=market,
                env_var=env_var,
                default_order=default_order,
                effective_order=list(registry.FALLBACK_CHAINS.get(market, default_order)),
                override=parsed or None,
                override_invalid=bool(parsed)
                and not registry.is_valid_source_order(market, parsed),
            )
        )
    return entries


def _validate_source_order_update(entry: SourceOrderUpdate) -> tuple[str, str]:
    """Validate one market reorder; return ``(env_var, dotenv value)``.

    A null/empty order — or one equal to the default — maps to an empty
    string, which clears any persisted override for that market.
    """
    from backtest.loaders import registry

    market = entry.market.strip()
    default_order = registry.get_default_source_order(market)
    if not default_order:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown market: {market!r}",
        )
    order = (
        [name.strip().lower() for name in entry.order if name.strip()]
        if entry.order
        else []
    )
    if order and not registry.is_valid_source_order(market, order):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid source order for {market}: must be a permutation of "
                f"the default chain {default_order}"
            ),
        )
    return (
        registry.source_order_env_var(market),
        "" if not order or order == default_order else ",".join(order),
    )


def _build_data_source_settings_response(
    values: Optional[Dict[str, str]] = None,
) -> DataSourceSettingsResponse:
    """Build the public data source settings payload."""
    host = _host()
    env_values = values if values is not None else _settings_store().read()
    token = env_values.get("TUSHARE_TOKEN", "")
    token_configured = host._is_configured_secret(token, TUSHARE_TOKEN_PLACEHOLDERS)
    gildata = env_values.get("GILDATA_TOKEN", "")
    gildata_configured = host._is_configured_secret(gildata, GILDATA_TOKEN_PLACEHOLDERS)
    # Late-access baostock helpers for monkeypatch compat.
    baostock_sup = getattr(host, "_baostock_supported", _baostock_supported)
    baostock_ins = getattr(host, "_baostock_installed", _baostock_installed)
    supported = baostock_sup()
    installed = baostock_ins()
    if supported:
        baostock_message = "BaoStock loader is available."
    elif installed:
        baostock_message = "BaoStock package is installed, but this project has no BaoStock loader."
    else:
        baostock_message = "No BaoStock loader is registered in this project."
    return DataSourceSettingsResponse(
        tushare_token_configured=token_configured,
        tushare_token_hint=None,
        gildata_token_configured=gildata_configured,
        gildata_token_hint=None,
        gildata_features=selected_features(),
        baostock_supported=supported,
        baostock_installed=installed,
        baostock_message=baostock_message,
        env_path=host._project_relative_path(host.ENV_PATH),
        source_orders=_build_source_orders(env_values),
    )


def _persist_settings_updates(updates: Dict[str, str], *, apply: bool = False) -> Dict[str, str]:
    try:
        return _settings_store().persist(updates, apply=apply)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Unable to save settings; check ownership and permissions for ~/.vibe-trading/.env") from exc


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_settings_routes(
    app: FastAPI,
    require_local_or_auth: AuthDep | None = None,
    require_settings_write_auth: AuthDep | None = None,
) -> None:
    """Mount the settings routes onto ``app``."""
    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")

    if host is None:
        raise RuntimeError(
            "register_settings_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    if require_local_or_auth is None:
        require_local_or_auth = host.require_local_or_auth
    if require_settings_write_auth is None:
        require_settings_write_auth = host.require_settings_write_auth

    # --- Routes ---

    @app.get(
        "/settings/llm",
        response_model=LLMSettingsResponse,
        dependencies=[Depends(require_local_or_auth)],
    )
    async def get_llm_settings():
        """Return project-local LLM settings for the Web UI."""
        # gh_cli / claude_cli providers shell out for their login status; keep
        # that off the event loop so open SSE streams are not stalled.
        return await asyncio.to_thread(_build_llm_settings_response)

    @app.put(
        "/settings/llm",
        response_model=LLMSettingsResponse,
        dependencies=[Depends(require_settings_write_auth)],
    )
    async def update_llm_settings(payload: UpdateLLMSettingsRequest):
        """Persist project-local LLM settings and update the running process."""
        host_ref = _host()
        provider_name = payload.provider.strip().lower()
        provider = LLM_PROVIDER_BY_NAME.get(provider_name)
        if provider_name == "custom":
            from src.providers.custom_profiles import active_provider_credentials

            active = active_provider_credentials()
            if (payload.model_name.strip() != active["model"]
                    or payload.base_url not in (None, active["base_url"])
                    or payload.api_key or payload.clear_api_key):
                raise HTTPException(status_code=400, detail="Edit and test a custom provider in the provider manager before activating it")
            provider = LLMProviderOption(name="custom", label="Custom (credential vault)", api_key_env=None,
                base_url_env="OPENAI_BASE_URL", default_model=active["model"], default_base_url=active["base_url"],
                auth_type="credential_vault", reasoning_efforts=[])
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported LLM provider"
            )

        model_name = payload.model_name.strip()
        if not model_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Model name is required"
            )

        if payload.temperature < 0 or payload.temperature > 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Temperature must be between 0 and 2",
            )

        reasoning_effort = (payload.reasoning_effort or "").strip().lower()
        if reasoning_effort and reasoning_effort not in provider.reasoning_efforts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Reasoning effort must be one of {', '.join(provider.reasoning_efforts)}, "
                    "or empty to leave it unset"
                ),
            )

        current_values = _settings_store().read()
        base_url = (
            payload.base_url if payload.base_url is not None else provider.default_base_url
        ).strip()
        if provider.auth_type == "oauth":
            try:
                from src.providers.openai_codex import validate_codex_base_url

                base_url = validate_codex_base_url(base_url)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
        updates: Dict[str, str] = {
            "LANGCHAIN_PROVIDER": provider.name,
            "LANGCHAIN_MODEL_NAME": model_name,
            provider.base_url_env: base_url,
            "LANGCHAIN_TEMPERATURE": str(payload.temperature),
            "TIMEOUT_SECONDS": str(payload.timeout_seconds),
            "MAX_RETRIES": str(payload.max_retries),
        }
        if reasoning_effort or "LANGCHAIN_REASONING_EFFORT" in current_values:
            updates["LANGCHAIN_REASONING_EFFORT"] = reasoning_effort

        if provider.api_key_env:
            if payload.clear_api_key:
                updates[provider.api_key_env] = ""
            elif payload.api_key is not None and payload.api_key.strip():
                api_key = payload.api_key.strip()
                updates[provider.api_key_env] = (
                    api_key
                    if host_ref._is_configured_secret(api_key, LLM_API_KEY_PLACEHOLDERS)
                    else ""
                )
            elif provider.api_key_env in current_values and host_ref._is_configured_secret(
                current_values[provider.api_key_env],
                LLM_API_KEY_PLACEHOLDERS,
            ):
                updates[provider.api_key_env] = current_values[provider.api_key_env]

        saved_values = _persist_settings_updates(updates, apply=True)
        return await asyncio.to_thread(_build_llm_settings_response, saved_values)

    @app.post(
        "/settings/llm/models",
        response_model=LLMModelsResponse,
        dependencies=[Depends(require_settings_write_auth)],
    )
    async def list_llm_models(payload: ListLLMModelsRequest):
        """Load provider model IDs for an editable UI combobox."""
        provider_name = payload.provider.strip().lower()
        provider = LLM_PROVIDER_BY_NAME.get(provider_name)
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported LLM provider"
            )
        if provider.auth_type == "claude_cli":
            # No HTTP endpoint: the base URL checks below would reject it outright.
            return await _list_claude_cli_models(provider, refresh=payload.refresh)
        if provider.name == "openai-codex":
            # OAuth credentials only go to our fixed Codex catalog endpoint.
            # Do not use base_url or api_key values supplied by the settings form.
            return await _list_openai_codex_models(provider)

        current_values = _settings_store().read()
        requested_base_url = (payload.base_url or "").strip()
        saved_base_url = (
            current_values.get(provider.base_url_env) or provider.default_base_url
        ).strip()
        try:
            base_url = _validate_model_base_url(requested_base_url or saved_base_url)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        api_key = (payload.api_key or "").strip()
        if not api_key and provider.api_key_env:
            trusted_base_urls = {
                _validate_model_base_url(candidate)
                for candidate in (
                    saved_base_url,
                    provider.default_base_url,
                    *provider.base_url_options,
                )
                if candidate.strip()
            }
            if not requested_base_url or base_url in trusted_base_urls:
                saved_key = current_values.get(provider.api_key_env, "").strip()
                if _host()._is_configured_secret(saved_key, LLM_API_KEY_PLACEHOLDERS):
                    api_key = saved_key
        return await _list_provider_models(
            provider,
            base_url=base_url,
            api_key=api_key,
        )

    @app.get(
        "/settings/data-sources",
        response_model=DataSourceSettingsResponse,
        dependencies=[Depends(require_local_or_auth)],
    )
    async def get_data_source_settings():
        """Return project-local data source credentials for the Web UI."""
        return _build_data_source_settings_response()

    @app.put(
        "/settings/data-sources",
        response_model=DataSourceSettingsResponse,
        dependencies=[Depends(require_settings_write_auth)],
    )
    async def update_data_source_settings(payload: UpdateDataSourceSettingsRequest):
        """Persist project-local data source credentials and update the running process."""
        host_ref = _host()
        current_values = _settings_store().read()
        updates: Dict[str, str] = {}

        if payload.clear_tushare_token:
            updates["TUSHARE_TOKEN"] = ""
        elif payload.tushare_token is not None and payload.tushare_token.strip():
            updates["TUSHARE_TOKEN"] = payload.tushare_token.strip()
        elif "TUSHARE_TOKEN" in current_values:
            updates["TUSHARE_TOKEN"] = current_values["TUSHARE_TOKEN"]

        if payload.clear_gildata_token:
            updates["GILDATA_TOKEN"] = ""
        elif payload.gildata_token is not None and payload.gildata_token.strip():
            updates["GILDATA_TOKEN"] = payload.gildata_token.strip()
        elif "GILDATA_TOKEN" in current_values:
            updates["GILDATA_TOKEN"] = current_values["GILDATA_TOKEN"]

        # Per-market source-order overrides: validate first (400 on a bad
        # permutation *before* anything is persisted), then merge only the
        # entries that actually change the dotenv (no-op saves don't grow
        # the file with 12 identical lines).
        order_updates: Dict[str, str] = {}
        if payload.source_orders is not None:
            for order_entry in payload.source_orders:
                env_var, value = _validate_source_order_update(order_entry)
                order_updates[env_var] = value
            for env_var, value in order_updates.items():
                if value != current_values.get(env_var, ""):
                    updates[env_var] = value

        if payload.gildata_features is not None:
            updates[FEATURES_ENV] = ",".join(dict.fromkeys(payload.gildata_features))

        if updates:
            saved_values = _persist_settings_updates(updates)
            for key, placeholders in (
                ("TUSHARE_TOKEN", TUSHARE_TOKEN_PLACEHOLDERS),
                ("GILDATA_TOKEN", GILDATA_TOKEN_PLACEHOLDERS),
            ):
                if key in updates:
                    token = updates[key].strip()
                    if host_ref._is_configured_secret(token, placeholders):
                        os.environ[key] = token
                    else:
                        os.environ.pop(key, None)
            if FEATURES_ENV in updates:
                os.environ[FEATURES_ENV] = updates[FEATURES_ENV]
            # Hot-apply source-order overrides in this process.
            for env_var, value in order_updates.items():
                if value:
                    os.environ[env_var] = value
                else:
                    os.environ.pop(env_var, None)
            if order_updates:
                from backtest.loaders import registry

                registry.refresh_source_order_overrides()
            reset_env_config()

        return _build_data_source_settings_response(
            saved_values if updates else _settings_store().read()
        )
