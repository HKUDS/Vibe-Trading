"""LLM and data-source settings HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_settings_routes(app, ...)``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys as _sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from src.config.accessor import get_env_value, reset_env_config

# Agent root (agent/) — resolved from this file's location (agent/src/api/).
_AGENT_DIR = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Pydantic models (defined locally -- NO shared modules, per maintainer rule)
# ---------------------------------------------------------------------------


class LLMProviderOption(BaseModel):
    """Supported LLM provider metadata for the settings UI."""

    name: str
    label: str
    api_key_env: Optional[str] = None
    base_url_env: str
    default_model: str
    default_base_url: str
    base_url_options: List[str] = Field(default_factory=list)
    api_key_required: bool = True
    auth_type: str = "api_key"
    login_command: Optional[str] = None


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


ModelDiscoveryWarningCode = Literal[
    "oauth_discovery_unsupported",
    "api_key_required",
    "model_list_unavailable",
]


class LLMModelsResponse(BaseModel):
    """Model IDs suitable for an editable settings combobox."""

    provider: str
    models: List[str]
    source: str
    warning_code: Optional[ModelDiscoveryWarningCode] = None


class DataSourceSettingsResponse(BaseModel):
    """Current data source credential settings."""

    tushare_token_configured: bool
    tushare_token_hint: Optional[str] = None
    baostock_supported: bool
    baostock_installed: bool
    baostock_message: str
    env_path: str


class UpdateDataSourceSettingsRequest(BaseModel):
    """Update project-local data source credentials."""

    tushare_token: Optional[str] = None
    clear_tushare_token: bool = False


# ---------------------------------------------------------------------------
# Provider metadata (settings-exclusive)
# ---------------------------------------------------------------------------

LLM_PROVIDER_CONFIG_PATH = _AGENT_DIR / "src" / "providers" / "llm_providers.json"


def _load_llm_providers() -> List[LLMProviderOption]:
    """Load provider metadata from JSON so additions stay data-driven."""
    try:
        raw = json.loads(LLM_PROVIDER_CONFIG_PATH.read_text(encoding="utf-8"))
        providers = [LLMProviderOption(**item) for item in raw]
    except Exception as exc:
        raise RuntimeError(f"Failed to load LLM provider config: {LLM_PROVIDER_CONFIG_PATH}") from exc

    seen: set[str] = set()
    for provider in providers:
        if provider.name in seen:
            raise RuntimeError(f"Duplicate LLM provider name: {provider.name}")
        seen.add(provider.name)
    if not providers:
        raise RuntimeError("LLM provider config must not be empty")
    return providers


LLM_PROVIDERS = _load_llm_providers()
LLM_PROVIDER_BY_NAME = {provider.name: provider for provider in LLM_PROVIDERS}
# "" leaves the setting unset (Off); "none" is an explicit value direct OpenAI
# needs to allow function tools on gpt-5.6-* models.
LLM_REASONING_EFFORTS = {"", "none", "low", "medium", "high", "max"}
LLM_API_KEY_PLACEHOLDERS = {"", "sk-or-v1-your-key-here", "sk-xxx", "xxx", "gsk_xxx"}
TUSHARE_TOKEN_PLACEHOLDERS = {"", "your-tushare-token"}


def _desktop_secure_credential_names() -> set[str]:
    """Return secrets owned by the desktop host when secure storage is active."""
    names = {"TUSHARE_TOKEN", "QVERIS_API_KEY"}
    names.update(
        provider.api_key_env for provider in LLM_PROVIDERS if provider.api_key_env
    )
    return names


def _desktop_secure_credentials_enabled() -> bool:
    return get_env_value("VIBE_TRADING_DESKTOP_SECURE_CREDENTIALS") == "1"


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


def _read_settings_env_values() -> Dict[str, str]:
    """Read settings without creating a dotenv file.

    Prefer the canonical user config, then the legacy package-local config.
    If neither exists, use ``agent/.env.example`` for display defaults only.
    """
    host = _host()
    env_path = host.ENV_PATH
    legacy_env_path = getattr(host, "LEGACY_ENV_PATH", _AGENT_DIR / ".env")
    env_example_path = host.ENV_EXAMPLE_PATH
    read_env = host._read_env_values
    if env_path.exists():
        values = read_env(env_path)
    elif legacy_env_path.exists():
        values = read_env(legacy_env_path)
    elif env_example_path.exists():
        values = read_env(env_example_path)
    else:
        values = {}

    if _desktop_secure_credentials_enabled():
        for name in _desktop_secure_credential_names():
            runtime_value = get_env_value(name)
            if runtime_value:
                values[name] = runtime_value
            else:
                values.pop(name, None)
    return values


def _model_list_url(base_url: str) -> str:
    """Return the OpenAI-compatible model-list endpoint for a provider URL."""
    url = base_url.strip().rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return f"{url}/models"


def _validate_model_base_url(base_url: str) -> str:
    """Accept HTTP(S) provider endpoints without embedded URL credentials."""
    normalized = base_url.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Provider base URL must be an HTTP(S) URL without embedded credentials")
    return normalized


def _extract_model_ids(payload: Any) -> List[str]:
    """Normalize common OpenAI-compatible model-list response shapes."""
    if not isinstance(payload, dict):
        return []
    records = payload.get("data")
    if not isinstance(records, list):
        records = payload.get("models")
    if not isinstance(records, list):
        return []

    model_ids: set[str] = set()
    for item in records:
        if isinstance(item, str):
            model_id = item.strip()
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("name") or "").strip()
        else:
            continue
        if model_id:
            model_ids.add(model_id)
    return sorted(model_ids, key=str.casefold)[:1000]


async def _list_provider_models(
    provider: LLMProviderOption,
    *,
    base_url: str,
    api_key: str,
) -> LLMModelsResponse:
    """Best-effort live model discovery with a safe editable fallback."""
    fallback = [provider.default_model]
    if provider.auth_type == "oauth":
        return LLMModelsResponse(
            provider=provider.name,
            models=fallback,
            source="default",
            warning_code="oauth_discovery_unsupported",
        )
    if provider.api_key_required and not api_key:
        return LLMModelsResponse(
            provider=provider.name,
            models=fallback,
            source="default",
            warning_code="api_key_required",
        )

    if provider.name == "ollama" and not base_url.rstrip("/").endswith("/v1"):
        base_url = f"{base_url.rstrip('/')}/v1"

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=False) as client:
            response = await client.get(_model_list_url(base_url), headers=headers)
            response.raise_for_status()
            models = _extract_model_ids(response.json())
    except (httpx.HTTPError, ValueError):
        return LLMModelsResponse(
            provider=provider.name,
            models=fallback,
            source="default",
            warning_code="model_list_unavailable",
        )

    discovered = bool(models)
    if provider.default_model not in models:
        models.insert(0, provider.default_model)
    return LLMModelsResponse(
        provider=provider.name,
        models=models or fallback,
        source="provider" if discovered else "default",
    )


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _build_llm_settings_response(
    values: Optional[Dict[str, str]] = None,
) -> LLMSettingsResponse:
    """Build the public settings payload from dotenv values."""
    host = _host()
    env_values = values if values is not None else _read_settings_env_values()
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
        providers=LLM_PROVIDERS,
    )


def _build_data_source_settings_response(
    values: Optional[Dict[str, str]] = None,
) -> DataSourceSettingsResponse:
    """Build the public data source settings payload."""
    host = _host()
    env_values = values if values is not None else _read_settings_env_values()
    token = env_values.get("TUSHARE_TOKEN", "")
    token_configured = host._is_configured_secret(token, TUSHARE_TOKEN_PLACEHOLDERS)
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
        baostock_supported=supported,
        baostock_installed=installed,
        baostock_message=baostock_message,
        env_path=host._project_relative_path(host.ENV_PATH),
    )


def _sync_runtime_env(provider: LLMProviderOption, updates: Dict[str, str]) -> None:
    """Apply saved LLM settings to the running API process."""
    host = _host()
    for key, value in updates.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)

    if provider.api_key_env:
        key_value = os.environ.get(provider.api_key_env, "")  # noqa: env-gate — dynamic provider api_key_env
        if host._is_configured_secret(key_value, LLM_API_KEY_PLACEHOLDERS):
            os.environ["OPENAI_API_KEY"] = key_value
        else:
            os.environ.pop("OPENAI_API_KEY", None)
    elif provider.auth_type == "oauth":
        os.environ.pop("OPENAI_API_KEY", None)
    else:
        os.environ["OPENAI_API_KEY"] = "ollama"

    base_url = os.environ.get(provider.base_url_env, "")  # noqa: env-gate — dynamic provider base_url_env
    if base_url:
        os.environ["OPENAI_API_BASE"] = base_url
        os.environ["OPENAI_BASE_URL"] = base_url
    else:
        os.environ.pop("OPENAI_API_BASE", None)
        os.environ.pop("OPENAI_BASE_URL", None)

    reset_env_config()


def _persist_settings_updates(updates: Dict[str, str]) -> Dict[str, str]:
    """Persist settings to the canonical user config with legacy migration.

    Args:
        updates: Environment keys to upsert.

    Returns:
        Effective values read back from the canonical dotenv.

    Raises:
        HTTPException: If the user config cannot be written.
    """
    host = _host()
    target = host.ENV_PATH
    legacy = getattr(host, "LEGACY_ENV_PATH", _AGENT_DIR / ".env")
    merged = dict(updates)
    if not target.exists() and legacy != target and legacy.exists():
        merged = {**host._read_env_values(legacy), **updates}
    if _desktop_secure_credentials_enabled():
        # Empty known secret keys in dotenv while preserving the decrypted
        # environment values injected by Electron for this process.
        merged.update({name: "" for name in _desktop_secure_credential_names()})
    try:
        host._write_env_values(target, merged)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Unable to save settings; check ownership and permissions for "
                "~/.vibe-trading/.env"
            ),
        ) from exc
    return _read_settings_env_values()


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
        return _build_llm_settings_response()

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
        if reasoning_effort not in LLM_REASONING_EFFORTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Reasoning effort must be none, low, medium, high, or max, "
                    "or empty to leave it unset"
                ),
            )

        current_values = _read_settings_env_values()
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
        elif payload.clear_api_key:
            os.environ.pop("OPENAI_API_KEY", None)

        saved_values = _persist_settings_updates(updates)
        _sync_runtime_env(provider, updates)
        return _build_llm_settings_response(saved_values)

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

        current_values = _read_settings_env_values()
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
        current_values = _read_settings_env_values()
        updates: Dict[str, str] = {}

        if payload.clear_tushare_token:
            updates["TUSHARE_TOKEN"] = ""
        elif payload.tushare_token is not None and payload.tushare_token.strip():
            updates["TUSHARE_TOKEN"] = payload.tushare_token.strip()
        elif "TUSHARE_TOKEN" in current_values:
            updates["TUSHARE_TOKEN"] = current_values["TUSHARE_TOKEN"]

        if updates:
            saved_values = _persist_settings_updates(updates)
            token = updates.get("TUSHARE_TOKEN", "").strip()
            if host_ref._is_configured_secret(token, TUSHARE_TOKEN_PLACEHOLDERS):
                os.environ["TUSHARE_TOKEN"] = token
            else:
                os.environ.pop("TUSHARE_TOKEN", None)
            reset_env_config()

        return _build_data_source_settings_response(
            saved_values if updates else _read_settings_env_values()
        )
