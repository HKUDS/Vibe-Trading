"""Build a provider SDK client from its resolved configuration snapshot."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy

import logging
import re
from typing import Any

from src.providers import request_guards
from src.providers.adapters import anthropic as anthropic_adapter
from src.providers.adapters import deepseek
from src.providers.adapters import openai as openai_adapter
from src.providers.adapters.reasoning import _sends_top_level_reasoning_effort, _validate_moonshot_reasoning_effort
from src.providers.registry import get_provider_capabilities
from src.providers.request_guards import _validate_authorization_credential, _validate_explicit_headers
from src.providers.settings import ProviderConfig, resolve_config


logger = logging.getLogger(__name__)


# Kimi reasoning models (K-series: kimi-k2*, kimi-k3, …, and the
# kimi-for-coding alias) reject any temperature other than 1 with
# "invalid temperature: only 1 is allowed for this model".
_KIMI_FORCED_TEMPERATURE_RE = re.compile(r"kimi-(k\d+|for-coding)", re.IGNORECASE)


def uses_responses_api(
    provider: str,
    configured_responses_api: bool | None,
    deepseek_adapter: str | None = None,
) -> bool:
    """Return whether the configured provider uses openai_adapter.ChatOpenAI's Responses route."""
    if configured_responses_api is not True:
        return False
    normalized_provider = provider.strip().lower().replace("_", "-")
    if normalized_provider in {"anthropic", "openai-codex"}:
        return False
    if normalized_provider != "deepseek":
        return True
    if deepseek_adapter is None:
        from src.config.accessor import get_env_value

        deepseek_adapter = get_env_value("VIBE_TRADING_DEEPSEEK_ADAPTER", "auto")
    adapter = deepseek._deepseek_adapter_mode(deepseek_adapter)
    if adapter == "openai-compatible":
        return True
    return adapter == "auto" and not deepseek._native_deepseek_adapter_available()


def build_llm(
    *,
    policy: ToolPolicy,
    model_name: str | None = None,
    callbacks: Any = None,
    snapshot: ProviderConfig | None = None,
) -> Any:
    """Construct the configured LangChain chat model.

    Args:
        snapshot: Resolved immutable config; defaults to current settings.
        model_name: Model name; defaults to LANGCHAIN_MODEL_NAME.
        callbacks: Optional LangChain callbacks.

    Returns:
        Provider-specific LangChain chat model.

    Raises:
        RuntimeError: If langchain-openai is missing or LANGCHAIN_MODEL_NAME is unset.
        ValueError: If a Moonshot kimi-k3.1 configuration carries a
            ``LANGCHAIN_REASONING_EFFORT`` outside the published
            low/high/max set.
    """
    snapshot = snapshot or resolve_config(model_name=model_name)
    name = model_name or snapshot.model
    if not name:
        raise RuntimeError("LANGCHAIN_MODEL_NAME is not set")
    provider = snapshot.provider
    caps = get_provider_capabilities(provider, name)
    options = snapshot.options
    temperature = options.langchain_temperature
    if snapshot.backend == "openai_codex":
        from src.providers.openai_codex import OpenAICodexLLM

        effort = options.langchain_reasoning_effort.strip().lower()
        return OpenAICodexLLM(
            roots=policy.file_roots,
            model=name,
            temperature=temperature,
            timeout=options.timeout_seconds,
            reasoning_effort=effort or None,
            codex_url=snapshot.base_url,
        )

    if snapshot.backend == "copilot":
        from src.providers.copilot_auth import CopilotSDKLLM

        return CopilotSDKLLM(model=name, timeout=options.timeout_seconds, token=snapshot.api_key)

    if snapshot.backend == "claude_cli":
        from src.providers.claude_cli import ClaudeCliLLM

        return ClaudeCliLLM(
            policy=policy,
            model=name,
            timeout=options.timeout_seconds,
            reasoning_effort=options.langchain_reasoning_effort.strip().lower(),
            environment=dict(snapshot.environment),
        )

    if snapshot.backend == "anthropic":
        return anthropic_adapter._build_anthropic(
            model=name,
            temperature=temperature,
            callbacks=callbacks,
            snapshot=snapshot,
            effort=options.langchain_reasoning_effort.strip().lower(),
        )

    if snapshot.backend == "deepseek":
        adapter_mode = deepseek._deepseek_adapter_mode(options.vibe_trading_deepseek_adapter)
        if adapter_mode != "openai-compatible":
            native_llm = deepseek._build_native_deepseek(
                model=name,
                temperature=temperature,
                callbacks=callbacks,
                snapshot=snapshot,
            )
            if native_llm is not None:
                return native_llm
            if adapter_mode == "native":
                raise RuntimeError("VIBE_TRADING_DEEPSEEK_ADAPTER=native requires langchain-deepseek")

    if openai_adapter.ChatOpenAI is None:
        raise RuntimeError("langchain-openai is not installed")
    # MiniMax requires temperature in (0.0, 1.0] — clamp to 0.01 when the
    # default 0.0 is used to avoid an API validation error.
    if provider == "minimax" and temperature <= 0.0:
        temperature = 0.01
    # Kimi reasoning models reject any temperature other than 1
    # ("invalid temperature: only 1 is allowed for this model").
    if (
        caps.name in {"moonshot", "kimi-coding"}
        and _KIMI_FORCED_TEMPERATURE_RE.match(name)
        and temperature != 1.0
    ):
        logger.info("Forcing temperature=1.0 for %s (provider requirement)", name)
        temperature = 1.0
    effort = options.langchain_reasoning_effort.strip().lower()
    # Moonshot/DeepSeek official APIs emit reasoning by default and ignore this field.
    configured_responses_api = options.langchain_use_responses_api
    use_responses_api = uses_responses_api(
        provider, configured_responses_api, options.vibe_trading_deepseek_adapter
    )
    _validate_moonshot_reasoning_effort(caps, name, effort, snapshot.base_url)
    api_key = snapshot.api_key
    _validate_authorization_credential(api_key, source=caps.api_key_env or "provider credential")
    kwargs: dict[str, Any] = {
        "model": name,
        "api_key": api_key,
        "base_url": snapshot.base_url or None,
        "temperature": temperature,
        "timeout": options.timeout_seconds,
        "max_retries": options.max_retries,
        "callbacks": callbacks,
        # Ask for real token usage on streamed calls (issue #1224); endpoints
        # that reject stream_options self-heal in _stream_with_usage_fallback.
        "stream_usage": True,
        "output_version": "responses/v1" if use_responses_api else None,
        "use_responses_api": use_responses_api,
        "reasoning": ({"effort": effort} if use_responses_api and effort else None),
        "extra_body": (
            {"reasoning": {"effort": effort}}
            if effort and not use_responses_api and caps.openrouter_reasoning_body
            else None
        ),
        "reasoning_effort": (
            effort
            if (
                effort
                and not use_responses_api
                and _sends_top_level_reasoning_effort(caps, name, snapshot.base_url)
            )
            else None
        ),
        "vibe_provider": provider,
        "vibe_api_key": api_key,
        "vibe_environment": snapshot.environment,
        "openai_proxy": snapshot.environment.get("OPENAI_PROXY", ""),
        "organization": snapshot.environment.get("OPENAI_ORG_ID")
        or snapshot.environment.get("OPENAI_ORGANIZATION", ""),
    }
    langchain_max_tokens = options.langchain_max_tokens
    if langchain_max_tokens:
        kwargs["max_tokens"] = langchain_max_tokens
    if caps.default_headers:
        headers = dict(caps.default_headers)
        if caps.name in {"moonshot", "kimi-coding"}:
            custom_ua = options.moonshot_user_agent.strip()
            if custom_ua:
                headers["User-Agent"] = custom_ua
        _validate_explicit_headers(headers, source=f"{caps.name} provider configuration")
        kwargs["default_headers"] = headers
    disable_proxy = options.vibe_trading_disable_http_proxy
    if provider == "custom":
        # Imported here: the guard needs httpx/httpcore/anyio, and the
        # background-tool lifecycle checks import this module without them.
        from src.providers.endpoint_guard import build_public_only_clients, proxy_applies
    clients = None
    explicit_proxy = snapshot.environment.get("OPENAI_PROXY", "")
    if provider == "custom" and (disable_proxy or not (explicit_proxy or proxy_applies(snapshot.base_url))):
        # A saved custom endpoint is re-checked on every connection, so a
        # host that re-resolves to a private address later is refused.
        clients = build_public_only_clients()
    elif disable_proxy:
        clients = request_guards._build_http_clients()
    elif explicit_proxy:
        clients = request_guards._build_http_clients(explicit_proxy)
    if clients:
        kwargs["http_client"], kwargs["http_async_client"] = clients
        kwargs["vibe_owned_http_clients"] = clients
        kwargs["openai_proxy"] = ""
    return openai_adapter.ChatOpenAIWithReasoning(**kwargs)
