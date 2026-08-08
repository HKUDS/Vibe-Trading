"""Provider capability definitions for OpenAI-compatible chat adapters."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Mapping, Optional


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
    default_headers: Mapping[str, str] = field(default_factory=dict)
    native_adapter_package: Optional[str] = None


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


_MOONSHOT_CAPABILITIES = ProviderCapabilities(
    "moonshot",
    "MOONSHOT_API_KEY",
    "MOONSHOT_BASE_URL",
    capture_reasoning=True,
    send_reasoning_content=True,
    normalize_assistant_content=True,
    default_headers={"User-Agent": _VIBE_USER_AGENT},
)

# Kimi for Coding subscription plan. Same wire behavior as Moonshot's open
# platform, but with a distinct endpoint/model and key namespace.
_KIMI_CODING_CAPABILITIES = ProviderCapabilities(
    "kimi-coding",
    "KIMI_CODING_API_KEY",
    "KIMI_CODING_BASE_URL",
    capture_reasoning=True,
    send_reasoning_content=True,
    normalize_assistant_content=True,
    default_headers={"User-Agent": _VIBE_USER_AGENT},
)

_NVIDIA_CAPABILITIES = ProviderCapabilities(
    "nvidia",
    "NVIDIA_API_KEY",
    "NVIDIA_BASE_URL",
    default_headers={"User-Agent": _VIBE_USER_AGENT},
)

# GLM thinking models (glm-4.5+/glm-5.x) stream the chain-of-thought as
# ``reasoning_content`` with the final answer in ``content``. Capture the
# reasoning like DeepSeek; do NOT replay it on assistant turns —
# ``send_reasoning_content`` stays off until verified live against bigmodel
# (DeepSeek rejects replayed reasoning; zhipu is unconfirmed). See #458.
_ZHIPU_CAPABILITIES = ProviderCapabilities(
    "zhipu",
    "ZHIPU_API_KEY",
    "ZHIPU_BASE_URL",
    capture_reasoning=True,
)

# iFlytek Spark's HTTP endpoint is plain OpenAI-compatible (Bearer APIPassword);
# the v1 chat path exposes no reasoning fields, so no capability flags are set.
_SPARK_CAPABILITIES = ProviderCapabilities(
    "spark",
    "SPARK_API_KEY",
    "SPARK_BASE_URL",
)

_OPENAI_CODEX_CAPABILITIES = ProviderCapabilities(
    "openai-codex", None, "OPENAI_CODEX_BASE_URL"
)


_PROVIDERS: dict[str, ProviderCapabilities] = {
    "openai": ProviderCapabilities("openai", "OPENAI_API_KEY", "OPENAI_BASE_URL"),
    "anthropic": ProviderCapabilities(
        "anthropic",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        native_adapter_package="langchain-anthropic",
    ),
    "openrouter": ProviderCapabilities(
        "openrouter",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        capture_reasoning=True,
        openrouter_reasoning_body=True,
    ),
    # Requesty is an OpenAI-compatible LLM gateway using the same
    # ``provider/model`` naming and the same opt-in ``extra_body.reasoning``
    # request option as OpenRouter, so it shares OpenRouter's capability shape.
    "requesty": ProviderCapabilities(
        "requesty",
        "REQUESTY_API_KEY",
        "REQUESTY_BASE_URL",
        capture_reasoning=True,
        openrouter_reasoning_body=True,
    ),
    "deepseek": ProviderCapabilities(
        "deepseek",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        capture_reasoning=True,
        native_adapter_package="langchain-deepseek",
    ),
    "siliconflow-cn": ProviderCapabilities(
        "siliconflow-cn",
        "SILICONFLOW_API_KEY",
        "SILICONFLOW_BASE_URL",
    ),
    "siliconflow-global": ProviderCapabilities(
        "siliconflow-global",
        "SILICONFLOW_GLOBAL_API_KEY",
        "SILICONFLOW_GLOBAL_BASE_URL",
    ),
    "nvidia": _NVIDIA_CAPABILITIES,
    "nvidia-nim": _NVIDIA_CAPABILITIES,
    "gemini": ProviderCapabilities(
        "gemini",
        "GEMINI_API_KEY",
        "GEMINI_BASE_URL",
        gemini_thought_signatures=True,
    ),
    "groq": ProviderCapabilities("groq", "GROQ_API_KEY", "GROQ_BASE_URL"),
    "dashscope": ProviderCapabilities(
        "dashscope", "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"
    ),
    "qwen": ProviderCapabilities("qwen", "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"),
    "zhipu": _ZHIPU_CAPABILITIES,
    "glm": _ZHIPU_CAPABILITIES,
    "moonshot": _MOONSHOT_CAPABILITIES,
    "kimi": _MOONSHOT_CAPABILITIES,
    "kimi-coding": _KIMI_CODING_CAPABILITIES,
    "minimax": ProviderCapabilities("minimax", "MINIMAX_API_KEY", "MINIMAX_BASE_URL"),
    "mimo": ProviderCapabilities("mimo", "MIMO_API_KEY", "MIMO_BASE_URL"),
    "spark": _SPARK_CAPABILITIES,
    "iflytek": _SPARK_CAPABILITIES,
    "zai": ProviderCapabilities("zai", "ZAI_API_KEY", "ZAI_BASE_URL"),
    "modelscope": ProviderCapabilities(
        "modelscope",
        "MODELSCOPE_API_KEY",
        "MODELSCOPE_BASE_URL",
    ),
    "ollama": ProviderCapabilities("ollama", None, "OLLAMA_BASE_URL"),
    "openai-codex": _OPENAI_CODEX_CAPABILITIES,
    "openai_codex": _OPENAI_CODEX_CAPABILITIES,
    "opencode-zen": ProviderCapabilities(
        "opencode-zen", "OPENAI_API_KEY", "OPENAI_BASE_URL"
    ),
    "opencode-go": ProviderCapabilities(
        "opencode-go", "OPENAI_API_KEY", "OPENAI_BASE_URL"
    ),
}


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


def get_provider_capabilities(
    provider: str | None = None,
    model: str | None = None,
) -> ProviderCapabilities:
    """Return the capability record for a provider/model pair.

    Args:
        provider: Configured provider name.
        model: Configured model name, used for direct test/adapter inference.

    Returns:
        Provider capability definition. Unknown providers fall back to OpenAI.

    Notes:
        Model-name inference (``_infer_from_model``) activates for the default
        ``"openai"`` provider and empty/None providers. Explicit non-OpenAI
        providers (OpenRouter, Requesty, DeepSeek, etc.) are never inferred —
        the explicit provider choice always wins.
    """
    normalized = (provider or "").strip().lower().replace("_", "-")
    if normalized == "openai-codex":
        return _PROVIDERS["openai-codex"]
    if normalized and normalized != "openai":
        return _PROVIDERS.get(normalized, _PROVIDERS["openai"])
    inferred = _infer_from_model(model or "")
    if inferred:
        return _PROVIDERS[inferred]
    return _PROVIDERS.get(normalized, _PROVIDERS["openai"])


def provider_env_names(
    provider: str | None, model: str | None = None
) -> tuple[str | None, str]:
    """Return the API-key and base-URL env names for a provider/model pair."""
    caps = get_provider_capabilities(provider, model)
    return caps.api_key_env, caps.base_url_env


_PROVIDER_CATALOG_PATH = Path(__file__).with_name("llm_providers.json")


@lru_cache(maxsize=1)
def _provider_default_base_urls() -> dict[str, str]:
    """Canonical ``name -> default_base_url`` map from the provider catalog.

    The catalog (``llm_providers.json``) declares each provider's canonical API
    root. Web Settings already fall back to it; this exposes the same default to
    the backend credential path so a CLI / manual-``.env`` user who sets only
    ``LANGCHAIN_PROVIDER`` + the API key still reaches the right endpoint (e.g.
    Z.ai's ``/api/coding/paas/v4``) instead of silently defaulting to
    ``api.openai.com`` and getting a 404 for a non-OpenAI model.
    """
    try:
        raw = json.loads(_PROVIDER_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = raw if isinstance(raw, list) else raw.get("providers", [])
    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip().lower()
        url = str(entry.get("default_base_url", "")).strip()
        if name and url:
            result[name] = url
    return result


def _provider_default_base_url(provider_name: str) -> str:
    """Return the catalog default base URL for a canonical provider name."""
    return _provider_default_base_urls().get((provider_name or "").strip().lower(), "")


def get_llm_credentials(
    provider: str | None,
    model: str | None,
) -> dict[str, str]:
    """Resolve API key, base URL, and model from provider/model env vars.

    Centralizes the ``provider → env_var_name → os.getenv → credential`` chain
    that was previously duplicated across ``_sync_provider_env()`` and
    ``provider_diagnostics()`` in ``llm.py``.

    Args:
        provider: Configured provider name (e.g. ``"openrouter"``).
        model: Configured model name (e.g. ``"deepseek/deepseek-v4-pro"``).

    Returns:
        Dict with ``"provider"``, ``"api_key"``, ``"base_url"``, ``"model"``
        keys. Values may be empty strings when not configured.

    Notes:
        Reads dynamic env vars via ``os.getenv`` — not part of ``EnvConfig``.
        When no base URL is set in the environment, falls back to the provider
        catalog's ``default_base_url`` so a provider set without an explicit
        ``*_BASE_URL`` still hits its canonical endpoint.
    """
    caps = get_provider_capabilities(provider, model)
    key_env, base_env = caps.api_key_env, caps.base_url_env

    if key_env is not None:
        api_key = os.getenv(  # noqa: env-gate
            key_env, ""
        ) or os.getenv(  # noqa: env-gate — dynamic provider key fallback
            "OPENAI_API_KEY", ""
        )
    else:
        api_key = (
            os.getenv("OPENAI_API_KEY", "")  # noqa: env-gate — ollama default key
            or "ollama"
        )

    base_url = (
        (
            os.getenv(base_env, "")  # noqa: env-gate — dynamic provider URL chain
            if base_env
            else ""
        )
        or os.getenv(  # noqa: env-gate — dynamic provider URL chain
            "OPENAI_BASE_URL", ""
        )
        or os.getenv(  # noqa: env-gate — dynamic provider URL chain
            "OPENAI_API_BASE", ""
        )
        or _provider_default_base_url(caps.name)
    )

    return {
        "provider": (provider or "").strip().lower(),
        "api_key": api_key,
        "base_url": base_url,
        "model": model or "",
    }
