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


def _points_at_official_host(caps: ProviderCapabilities, base_url: str) -> bool:
    """Report whether a provider that lists official hosts is actually talking to one of them."""
    if not caps.official_hosts or not base_url:
        return True
    host = urlparse(base_url if "//" in base_url else f"https://{base_url}").hostname or ""
    return host.lower() in caps.official_hosts


def _sends_top_level_reasoning_effort(caps: ProviderCapabilities, model: str | None = None, base_url: str = "") -> bool:
    """Combine the allowlist flag with the endpoint-host check."""
    return _supports_top_level_reasoning_effort(caps, model) and _points_at_official_host(caps, base_url)


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
