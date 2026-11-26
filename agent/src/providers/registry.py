"""Shared, credential-free provider catalog for runtime, CLI and Web settings."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Mapping, Optional

CATALOG_PATH = Path(__file__).with_name("llm_providers.json")
DEFAULT_REASONING_EFFORTS = ("none", "low", "medium", "high", "max")
_BACKENDS = {"openai_compatible", "openai_codex", "copilot", "claude_cli", "anthropic", "deepseek"}


@lru_cache(maxsize=1)
def _catalog() -> tuple[dict[str, Any], ...]:
    """Load and validate the bundled catalog, failing visibly on invalid data."""
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("LLM provider catalog must be a non-empty list")
    seen: set[str] = set()
    for row in raw:
        for key in ("name", "label", "base_url_env", "default_model", "default_base_url"):
            if not isinstance(row.get(key), str):
                raise ValueError(f"Invalid provider catalog field: {key}")
        if row.get("backend", "openai_compatible") not in _BACKENDS:
            raise ValueError(f"Unknown provider backend: {row['name']}")
        for name in (row["name"], *row.get("aliases", []), *row.get("runtime_variants", {})):
            if name in seen:
                raise ValueError(f"Duplicate LLM provider name: {name}")
            seen.add(name)
    return tuple(raw)


def provider_catalog() -> list[dict[str, Any]]:
    """Return independent public metadata records without runtime-only fields.

    Returns:
        Independent copies of the public provider records with defaults for backend and automatic
        model listing.
    """
    private = {"capabilities", "aliases", "runtime_variants", "setup", "onboarding", "model_capabilities",
               "infer_model_prefixes", "infer_model_substrings"}
    return [
        {"backend": "openai_compatible", "automatic_model_list": False,
         **deepcopy({k: v for k, v in row.items() if k not in private})}
        for row in _catalog()
    ]


def provider_names() -> frozenset[str]:
    """Public identifiers, including legacy aliases, safe for runtime metadata.

    Returns:
        The set of catalog provider names, aliases, and runtime variants.
    """
    return frozenset(
        name
        for row in _catalog()
        for name in (row["name"], *row.get("aliases", ()), *row.get("runtime_variants", {}))
    )


def provider_requires_key(provider: str) -> bool:
    """Report whether a catalog provider needs an API key.

    Args:
        provider: Catalog name, alias or runtime variant.

    Returns:
        The catalog row's api_key_required flag, or True for a name the catalog does not list.
    """
    for row in _catalog():
        if provider in (row["name"], *row.get("aliases", ()), *row.get("runtime_variants", {})):
            return bool(row["api_key_required"])
    return True


def setup_choices() -> list[dict[str, Any]]:
    """Build the catalog entries shown in legacy setup.

    Returns:
        Setup entries in configured order with labels, model and endpoint defaults, and credential
        field hints.
    """
    rows = sorted((r for r in _catalog() if r.get("setup")), key=lambda r: r["setup"]["order"])
    return [
        {
            "provider": r["name"],
            "label": r["setup"].get("label", r["label"]),
            "key_env": r.get("api_key_env"),
            "base_env": r["base_url_env"],
            "model": r["default_model"],
            "base_url": r["default_base_url"],
            "key_prefix": r["setup"].get("key_prefix"),
            "key_placeholder": r["setup"].get("key_placeholder"),
        }
        for r in rows
    ]


def onboarding_choices() -> list[dict[str, Any]]:
    """Project first-launch wizard options while preserving its ordering.

    Returns:
        Wizard options in configured order, including default endpoints and deduplicated suggested
        models.
    """
    rows = sorted((r for r in _catalog() if r.get("onboarding")), key=lambda r: r["onboarding"]["order"])
    return [
        {
            "key": r["name"],
            "label": r["onboarding"].get("label", r["label"]),
            "description": r["onboarding"].get("description", ""),
            "default_model": r["default_model"],
            "key_env": r.get("api_key_env"),
            "base_env": r["base_url_env"],
            "base_url": r["default_base_url"],
            "key_prefix": r["onboarding"].get("key_prefix"),
            "suggested_models": tuple(dict.fromkeys([r["default_model"], *r.get("model_options", [])])),
        }
        for r in rows
    ]


@dataclass(frozen=True)
class ProviderCapabilities:
    """Declare verified endpoint capabilities for all models or selected model prefixes."""

    name: str
    api_key_env: Optional[str]
    base_url_env: str
    capture_reasoning: bool = False
    send_reasoning_content: bool = False
    gemini_thought_signatures: bool = False
    normalize_assistant_content: bool = False
    openrouter_reasoning_body: bool = False
    top_level_reasoning_effort: bool = False
    reasoning_effort_models: tuple[str, ...] | None = None
    default_headers: Mapping[str, str] = field(default_factory=dict)
    native_adapter_package: Optional[str] = None
    default_base_url: str = ""
    backend: str = "openai_compatible"
    official_hosts: tuple[str, ...] = ()
    min_temperature: Optional[float] = None
    forced_temperature: Optional[float] = None
    forced_temperature_models: Optional[str] = None
    moonshot_user_agent: bool = False


_DISTRIBUTION_NAME = "vibe-trading-ai"


def _package_version() -> str:
    """Return the installed distribution version for User-Agent headers."""
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return "dev"


_VIBE_USER_AGENT = f"Vibe-Trading/{_package_version()}"


def _infer_from_model(model: str) -> str | None:
    """Name the provider a bare model id implies: catalog prefixes first, then substrings."""
    lowered = model.strip().lower()
    if not lowered:
        return None
    for key, matches in (("infer_model_prefixes", str.startswith), ("infer_model_substrings", str.__contains__)):
        for row in _catalog():
            if any(matches(lowered, marker) for marker in row.get(key, ())):
                return row["name"]
    return None


@lru_cache(maxsize=256)
def get_provider_capabilities(provider: str | None = None, model: str | None = None) -> ProviderCapabilities:
    """Read one provider's connection and protocol facts, preserving legacy inference.

    Args:
        provider: Provider label or alias. An empty or OpenAI label allows inference from the model.
        model: Model name used for inference and model-specific overrides.

    Returns:
        Connection defaults and protocol capabilities for the resolved provider, falling back to
        OpenAI for unknown names.
    """
    name = (provider or "").strip().lower().replace("_", "-")
    if name == "custom":
        return ProviderCapabilities("custom", None, "OPENAI_BASE_URL", capture_reasoning=True)
    if name in {"", "openai"}:
        name = _infer_from_model(model or "") or "openai"
    for row in _catalog():
        if name in row.get("runtime_variants", {}):
            return ProviderCapabilities(**row["runtime_variants"][name])
        if name in row.get("aliases", ()):
            return get_provider_capabilities(row["name"], model)
        if name != row["name"]:
            continue
        caps = deepcopy({**row.get("capabilities", {}), **row.get("model_capabilities", {}).get(model, {})})
        caps["default_headers"] = {
            k: v.replace("{user_agent}", _VIBE_USER_AGENT) for k, v in caps.get("default_headers", {}).items()
        }
        for key in ("reasoning_effort_models", "official_hosts"):
            if caps.get(key) is not None:
                caps[key] = tuple(caps[key])
        return ProviderCapabilities(
            caps.pop("name", name), row.get("api_key_env"), row["base_url_env"],
            default_base_url=row["default_base_url"], backend=row.get("backend", "openai_compatible"), **caps,
        )
    return get_provider_capabilities("openai")


def provider_env_names(provider: str | None, model: str | None = None) -> tuple[str | None, str]:
    """Return the API-key and base-URL env names for a provider/model pair.

    Args:
        provider: Provider label or alias.
        model: Optional model used for provider inference.

    Returns:
        The API key environment variable, or None for an adapter without one, and the base URL
        environment variable.
    """
    caps = get_provider_capabilities(provider, model)
    return caps.api_key_env, caps.base_url_env
