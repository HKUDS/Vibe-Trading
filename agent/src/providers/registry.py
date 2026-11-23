"""Shared, credential-free provider catalog for runtime, CLI and Web settings.

Protocol exceptions live in adapters; declarative provider facts live in
``llm_providers.json``. Reading this module never loads credentials or SDKs.
"""

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
    """Return independent public metadata records without runtime-only fields."""
    private = {"capabilities", "aliases", "runtime_variants", "setup", "onboarding"}
    return [
        {"backend": "openai_compatible", "automatic_model_list": False,
         **deepcopy({k: v for k, v in row.items() if k not in private})}
        for row in _catalog()
    ]


def provider_names() -> frozenset[str]:
    """Public identifiers, including legacy aliases, safe for runtime metadata."""
    return frozenset(
        name
        for row in _catalog()
        for name in (row["name"], *row.get("aliases", ()), *row.get("runtime_variants", {}))
    )


def setup_choices() -> list[dict[str, Any]]:
    """Project legacy setup options without duplicating models or endpoints."""
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
    """Project first-launch wizard options while preserving its ordering."""
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
    """Provider-specific payload and diagnostic behavior.

    Args:
        name: Canonical provider name.
        api_key_env: Provider-specific API key environment variable.
        base_url_env: Provider-specific base URL environment variable.
        capture_reasoning: Whether inbound reasoning fields should be preserved.
        send_reasoning_content: Whether outbound assistant history must include
            ``reasoning_content``.
        gemini_thought_signatures: Whether Gemini OpenAI-compatible tool-call
            thought signatures should be round-tripped.
        normalize_assistant_content: Whether assistant ``content=None`` should
            be normalized to ``""`` for strict providers.
        openrouter_reasoning_body: Whether ``extra_body.reasoning`` is a valid
            OpenRouter request option.
        top_level_reasoning_effort: Whether the provider accepts a top-level
            ``reasoning_effort`` field on ``/v1/chat/completions``. **A positive
            allowlist, and it stays one.** Speaking the OpenAI wire format does
            not imply accepting every OpenAI field: an endpoint that validates
            its request body strictly rejects the unknown key and the call
            fails, so a provider gets this only once someone has watched a real
            request to it succeed. Leave it False until then — the cost of False
            is that ``LANGCHAIN_REASONING_EFFORT`` has no effect there, and the
            cost of a wrong True is that every request fails.
        reasoning_effort_models: Optional per-model scoping for
            ``top_level_reasoning_effort``. ``None`` (the default) means every
            model of the provider accepts the field; a tuple means only models
            whose name starts with one of the entries do — prefixes, so
            ``"kimi-k3.1-pro"`` also covers ``kimi-k3.1-pro-highspeed``. An
            unmatched model is a no-op, not an error, mirroring the asymmetry
            of the provider-level flag. Ignored when the flag is False.
        default_headers: Provider-scoped headers passed to ChatOpenAI.
        native_adapter_package: Optional native adapter package to report.
    """

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


# Distribution name from pyproject.toml [project].name.
_DISTRIBUTION_NAME = "vibe-trading-ai"


def _package_version() -> str:
    """Return the installed distribution version for User-Agent headers.

    Returns:
        Installed ``vibe-trading-ai`` version string, or ``"dev"`` when the
        package metadata is unavailable (e.g. an uninstalled source checkout).
    """
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return "dev"


_VIBE_USER_AGENT = f"Vibe-Trading/{_package_version()}"


def _infer_from_model(model: str) -> str | None:
    lowered = model.strip().lower()
    if not lowered:
        return None
    if lowered.startswith("gemini"):
        return "gemini"
    if lowered.startswith("deepseek"):
        return "deepseek"
    if lowered.startswith("nvidia/"):
        return "nvidia"
    if lowered.startswith("glm"):
        return "zhipu"
    if "kimi" in lowered or "moonshot" in lowered:
        return "moonshot"
    return None


@lru_cache(maxsize=256)
def get_provider_capabilities(provider: str | None = None, model: str | None = None) -> ProviderCapabilities:
    """Read one provider's connection and protocol facts, preserving legacy inference."""
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
        caps = deepcopy(row.get("capabilities", {}))
        if name == "minimax" and model == "MiniMax-M3.1-Flash":
            caps = {"capture_reasoning": True, "send_reasoning_content": True}
        caps["default_headers"] = {
            k: v.replace("{user_agent}", _VIBE_USER_AGENT) for k, v in caps.get("default_headers", {}).items()
        }
        if caps.get("reasoning_effort_models") is not None:
            caps["reasoning_effort_models"] = tuple(caps["reasoning_effort_models"])
        return ProviderCapabilities(
            caps.pop("name", name), row.get("api_key_env"), row["base_url_env"],
            default_base_url=row["default_base_url"], backend=row.get("backend", "openai_compatible"), **caps,
        )
    return get_provider_capabilities("openai")


def provider_env_names(provider: str | None, model: str | None = None) -> tuple[str | None, str]:
    """Return the API-key and base-URL env names for a provider/model pair."""
    caps = get_provider_capabilities(provider, model)
    return caps.api_key_env, caps.base_url_env
