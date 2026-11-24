"""OpenAI-compatible reasoning-effort capabilities and validation."""

from __future__ import annotations

from urllib.parse import urlparse

from src.providers.registry import ProviderCapabilities


def _supports_top_level_reasoning_effort(caps: ProviderCapabilities, model: str | None = None) -> bool:
    """Report whether a provider accepts a top-level ``reasoning_effort`` field."""
    if not caps.top_level_reasoning_effort or caps.openrouter_reasoning_body:
        return False
    models = caps.reasoning_effort_models
    if models is None:
        return True
    lowered = (model or "").strip().lower()
    return any(lowered.startswith(prefix) for prefix in models)


def _openai_label_points_at_openai(caps: ProviderCapabilities, base_url: str) -> bool:
    """Report whether the OpenAI capability is actually talking to OpenAI."""
    if caps.name != "openai":
        return True
    if not base_url:
        return True
    host = urlparse(base_url if "//" in base_url else f"https://{base_url}").hostname or ""
    return host.lower() in {"api.openai.com", "openai.com"}


def _moonshot_label_points_at_moonshot(caps: ProviderCapabilities, base_url: str) -> bool:
    """Report whether the Moonshot capability is actually talking to Moonshot."""
    if caps.name != "moonshot":
        return True
    if not base_url:
        return True
    host = urlparse(base_url if "//" in base_url else f"https://{base_url}").hostname or ""
    return host.lower() == "api.moonshot.ai"


def _sends_top_level_reasoning_effort(caps: ProviderCapabilities, model: str | None = None, base_url: str = "") -> bool:
    """Combine the allowlist flag with the endpoint-host checks."""
    return (
        _supports_top_level_reasoning_effort(caps, model)
        and _openai_label_points_at_openai(caps, base_url)
        and _moonshot_label_points_at_moonshot(caps, base_url)
    )


_MOONSHOT_REASONING_EFFORT_LEVELS = ("low", "high", "max")


def _validate_moonshot_reasoning_effort(
    caps: ProviderCapabilities, model: str, effort: str, base_url: str = ""
) -> None:
    """Reject an effort level the kimi-k3.1 API would reject (issue #2020)."""
    if caps.name != "moonshot" or not effort:
        return
    if not _sends_top_level_reasoning_effort(caps, model, base_url):
        return
    if effort in _MOONSHOT_REASONING_EFFORT_LEVELS:
        return
    accepted = ", ".join(repr(level) for level in _MOONSHOT_REASONING_EFFORT_LEVELS)
    raise ValueError(
        f"LANGCHAIN_REASONING_EFFORT={effort!r} is not valid for {model} on "
        f"api.moonshot.ai: kimi-k3.1 accepts only {accepted}. There is no "
        "'medium' or 'minimal' level "
        "(https://platform.kimi.ai/docs/guide/use-reasoning-effort.md)."
    )
