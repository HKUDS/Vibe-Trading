"""OpenAI-compatible reasoning-effort capabilities and validation."""

from __future__ import annotations

from urllib.parse import urlparse

from src.providers.registry import ProviderCapabilities


def _supports_top_level_reasoning_effort(caps: ProviderCapabilities, model: str | None = None) -> bool:
    """Report whether a provider accepts a top-level ``reasoning_effort`` field.

    Reads the ``top_level_reasoning_effort`` capability flag, which is a
    positive allowlist: a provider is listed only once a real request to it has
    been observed to succeed or its published contract documents the field (the
    Moonshot kimi-k3.1 entry, issue #2020). Speaking the OpenAI wire format
    does not imply accepting every OpenAI field, and an endpoint that validates
    its body strictly rejects the unknown key outright — so the default is off
    and the consequence of that default is a no-op, not a failed call.

    Providers carrying ``reasoning_effort_models`` scope the field further to
    those model-name prefixes; an unmatched model is a no-op, not an error,
    the same asymmetry the provider-level flag has.

    Relays that take the effort inside ``extra_body.reasoning`` (OpenRouter)
    use that path instead and are excluded here.

    Args:
        caps: Canonical capabilities resolved for the provider and model. Note
            this is the *resolved* capability, so provider ``openai`` with a
            ``deepseek-*`` model arrives here as DeepSeek, and an unrecognised
            provider name arrives as OpenAI — which is why callers must also
            check the base URL before trusting the OpenAI entry.
        model: Model name the request would carry, matched against
            ``reasoning_effort_models`` when the provider sets one. Only the
            Moonshot entry sets one today.

    Returns:
        True when the provider is on the allowlist, the model is covered by
        the provider's model scoping (if any), and the provider does not use
        the ``extra_body.reasoning`` relay path.
    """
    if not caps.top_level_reasoning_effort or caps.openrouter_reasoning_body:
        return False
    models = caps.reasoning_effort_models
    if models is None:
        return True
    lowered = (model or "").strip().lower()
    return any(lowered.startswith(prefix) for prefix in models)


def _openai_label_points_at_openai(caps: ProviderCapabilities, base_url: str) -> bool:
    """Report whether the OpenAI capability is actually talking to OpenAI.

    An unknown ``LANGCHAIN_PROVIDER`` falls back to the OpenAI capabilities, and
    a base-URL override points the OpenAI client at some other gateway (Ollama,
    LiteLLM, a corporate proxy). Those speak the OpenAI wire format but need not
    accept ``reasoning_effort``, so the label alone is not enough to send it.

    Non-OpenAI capabilities are unaffected — they carry their own endpoint.
    """
    if caps.name != "openai":
        return True
    if not base_url:
        return True
    host = urlparse(base_url if "//" in base_url else f"https://{base_url}").hostname or ""
    return host.lower() in {"api.openai.com", "openai.com"}


def _moonshot_label_points_at_moonshot(caps: ProviderCapabilities, base_url: str) -> bool:
    """Report whether the Moonshot capability is actually talking to Moonshot.

    Mirrors ``_openai_label_points_at_openai``: ``MOONSHOT_BASE_URL`` can point
    the provider at a relay or a self-hosted gateway that speaks the OpenAI
    wire format without promising to accept ``reasoning_effort``, and the
    kimi-k3.1 contract (issue #2020) is published for api.moonshot.ai only.
    Non-Moonshot capabilities are unaffected.
    """
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
    """Reject an effort level the kimi-k3.1 API would reject (issue #2020).

    Moonshot publishes ``reasoning_effort`` for kimi-k3.1 as one of
    ``low``/``high``/``max`` — there is no ``medium`` or ``minimal`` — and an
    unknown value fails the request server-side. When the field is about to be
    sent (Moonshot capabilities, a covered model, the official endpoint), a
    value outside the published set is a configuration error and fails here,
    where the message names the accepted values, instead of surfacing as an
    opaque API 400 on the first call. Configurations the field is never sent
    to — other models, relays, other providers — are not validated.
    """
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
