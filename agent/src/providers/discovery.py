"""Provider model discovery shared by application entry points, without HTTP routing."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from src.providers.registry import DEFAULT_REASONING_EFFORTS, provider_catalog

logger = logging.getLogger(__name__)


class LLMProviderOption(BaseModel):
    """Supported LLM provider metadata for the settings UI."""

    name: str
    backend: str = "openai_compatible"
    automatic_model_list: bool = False
    label: str
    api_key_env: Optional[str] = None
    base_url_env: str
    default_model: str
    model_options: List[str] = Field(default_factory=list)
    default_base_url: str
    base_url_options: List[str] = Field(default_factory=list)
    api_key_required: bool = True
    auth_type: str = "api_key"
    login_command: Optional[str] = None
    # Levels the settings form offers and the update route accepts; "" (unset)
    # is always allowed on top of these.
    reasoning_efforts: List[str] = Field(default_factory=lambda: list(DEFAULT_REASONING_EFFORTS))


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
    # Model id -> reasoning effort levels it accepts; an empty list means the
    # model takes no effort setting. Only providers that report it fill this.
    effort_levels: Optional[Dict[str, List[str]]] = None
    # Optional display metadata. IDs remain canonical and editable.
    model_labels: Optional[Dict[str, str]] = None
    default_effort_levels: Optional[Dict[str, str]] = None


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


# Codex CLI model discovery requires a client_version query parameter. Keep
# this value explicit and review it when updating Codex OAuth compatibility.
# Verified with the ChatGPT Codex catalog on 2026-10-27.
_CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models"
_CODEX_MODELS_CLIENT_VERSION = "0.159.0"
_CODEX_EFFORT_LEVELS = frozenset(
    next(p["reasoning_efforts"] for p in provider_catalog() if p["name"] == "openai-codex")
)


async def _list_openai_codex_models(provider: LLMProviderOption) -> LLMModelsResponse:
    """Discover ChatGPT OAuth models without sharing the token with form URLs."""
    from src.providers.openai_codex import _build_headers, _get_codex_token

    fallback = LLMModelsResponse(
        provider=provider.name,
        models=[provider.default_model],
        source="default",
        warning_code="model_list_unavailable",
    )
    try:
        token = await asyncio.to_thread(_get_codex_token)
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=False, trust_env=False) as client:
            for attempt in range(2):
                headers = _build_headers(token.account_id, token.access)
                headers["Accept"] = "application/json"
                response = await client.get(
                    _CODEX_MODELS_URL,
                    params={"client_version": _CODEX_MODELS_CLIENT_VERSION},
                    headers=headers,
                )
                if response.status_code == 401 and attempt == 0:
                    token = await asyncio.to_thread(_get_codex_token, force_refresh=True, rejected_access=token.access)
                    continue
                response.raise_for_status()
                payload = response.json()
                break
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            return fallback

        models: list[str] = []
        efforts: dict[str, list[str]] = {}
        labels: dict[str, str] = {}
        defaults: dict[str, str] = {}
        for item in payload["models"][:1000]:
            if not isinstance(item, dict):
                continue
            # supported_in_api is an API-key catalog filter, not a ChatGPT
            # entitlement check (Codex ModelPreset::filter_by_auth).
            if item.get("visibility") != "list":
                continue
            slug = item.get("slug")
            if not isinstance(slug, str) or not slug or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", slug):
                continue
            model_id = f"openai-codex/{slug}"
            if model_id in models:
                continue
            models.append(model_id)
            label = item.get("display_name")
            if isinstance(label, str) and label.strip():
                labels[model_id] = label.strip()[:128]
            levels = item.get("supported_reasoning_levels")
            if isinstance(levels, list):
                supported = []
                for level in levels:
                    effort = level.get("effort") if isinstance(level, dict) else None
                    if isinstance(effort, str) and effort in _CODEX_EFFORT_LEVELS and effort not in supported:
                        supported.append(effort)
                efforts[model_id] = supported
            default = item.get("default_reasoning_level")
            if (
                isinstance(default, str)
                and default in _CODEX_EFFORT_LEVELS
                and (model_id not in efforts or default in efforts[model_id])
            ):
                defaults[model_id] = default
        if not models:
            return fallback
        return LLMModelsResponse(
            provider=provider.name,
            models=models,
            source="provider",
            effort_levels=efforts,
            model_labels=labels,
            default_effort_levels=defaults,
        )
    except (RuntimeError, AttributeError, httpx.HTTPError, ValueError, TypeError) as exc:
        # Never log exception bodies here: the HTTP response could contain secrets.
        logger.warning("OpenAI Codex model discovery unavailable (%s)", type(exc).__name__)
        return fallback


async def _list_provider_models(
    provider: LLMProviderOption,
    *,
    base_url: str,
    api_key: str,
) -> LLMModelsResponse:
    """Best-effort live model discovery with a safe editable fallback."""
    fallback = LLMModelsResponse(provider=provider.name, models=[provider.default_model], source="default")
    # Keep the direct MiniMax picker curated; custom endpoints still discover.
    if provider.name == "minimax" and base_url.rstrip("/") in provider.base_url_options:
        fallback.models = provider.model_options or fallback.models
        return fallback
    if provider.auth_type in {"oauth", "gh_cli"}:
        fallback.warning_code = "oauth_discovery_unsupported"
        return fallback
    if provider.api_key_required and not api_key:
        fallback.warning_code = "api_key_required"
        return fallback

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
        fallback.warning_code = "model_list_unavailable"
        return fallback

    # Prefer configured recommendations without deleting discovered routes.
    # Paid variants, legacy models and future releases remain selectable.
    official_endpoints = {provider.default_base_url, *provider.base_url_options}
    if base_url.rstrip("/") in official_endpoints:
        preferred = [model for model in provider.model_options if model in models]
        models = preferred + [model for model in models if model not in preferred]

    discovered = bool(models)
    if provider.default_model not in models:
        models.insert(0, provider.default_model)
    return LLMModelsResponse(
        provider=provider.name,
        models=models,
        source="provider" if discovered else "default",
    )


async def _list_claude_cli_models(provider: LLMProviderOption, *, refresh: bool) -> LLMModelsResponse:
    """List the models the local Claude Code login can run, with their effort levels."""
    from src.providers.claude_cli import list_claude_cli_models

    try:
        discovered = await asyncio.to_thread(list_claude_cli_models, refresh=refresh)
    except RuntimeError as exc:
        logger.warning("claude-cli model list unavailable: %s", exc)
        return LLMModelsResponse(
            provider=provider.name,
            models=[provider.default_model],
            source="default",
            warning_code="model_list_unavailable",
        )
    models = [model.model_id for model in discovered]
    if provider.default_model not in models:
        models.insert(0, provider.default_model)
    return LLMModelsResponse(
        provider=provider.name,
        models=models,
        source="provider",
        effort_levels={model.model_id: list(model.effort_levels) for model in discovered},
    )
