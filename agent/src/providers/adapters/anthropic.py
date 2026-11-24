"""Anthropic request construction, prompt caching and parameter negotiation."""

from __future__ import annotations

import logging
import re
from functools import partial
from importlib import import_module
from typing import Any, Dict, List

from src.kernel import contracts
from src.providers import request_guards
from src.providers.adapters.common import (
    _default_async_client_is_instance_owned, _endpoint_model, retry_async_request, retry_async_stream, retry_request, retry_stream,
)
from src.providers.request_guards import _guard_provider_redirects


logger = logging.getLogger(__name__)


# Learn endpoint/model temperature support from actual rejections (#1223).
_ANTHROPIC_TEMPERATURE_UNSUPPORTED: set[tuple[str, str, str]] = set()


_TEMPERATURE_SAFE_ANTHROPIC_CACHE: dict[type, type] = {}


def _is_anthropic_temperature_unsupported_error(exc: BaseException) -> bool:
    """Return True when an Anthropic error reports `temperature` as unsupported."""
    message = str(getattr(exc, "message", "") or exc).lower()
    if "temperature" not in message:
        return False
    return (
        "deprecated" in message
        or "not supported" in message
        or "unsupported" in message
        or "not allowed" in message
        # Match field validation without treating unrelated errors as rejections.
        or re.search(r"(?<![\w.])temperature[\"'`]*\s*:\s*extra inputs are not permitted\b", message)
        is not None
    )


def _remember_temperature_rejection(client: Any, exc: BaseException) -> bool:
    endpoint = _endpoint_model(client)
    if endpoint in _ANTHROPIC_TEMPERATURE_UNSUPPORTED or not _is_anthropic_temperature_unsupported_error(exc):
        return False
    logger.info(
        "Model %s rejects `temperature`; retrying without it and omitting it for subsequent calls.",
        endpoint[2],
    )
    _ANTHROPIC_TEMPERATURE_UNSUPPORTED.add(endpoint)
    return True


def _make_temperature_safe_anthropic(base_cls: type) -> type:
    """Build (and cache) a ChatAnthropic subclass that self-heals temperature."""
    cached = _TEMPERATURE_SAFE_ANTHROPIC_CACHE.get(base_cls)
    if cached is not None:
        return cached

    def _get_request_payload(self: Any, *args: Any, **kwargs: Any) -> dict:
        payload = base_cls._get_request_payload(self, *args, **kwargs)
        if isinstance(payload, dict) and _endpoint_model(self) in _ANTHROPIC_TEMPERATURE_UNSUPPORTED:
            payload.pop("temperature", None)
            # The SDK merges extra_body into the request, so remove temperature there too.
            extra_body = payload.get("extra_body")
            if isinstance(extra_body, dict) and "temperature" in extra_body:
                extra_body = {k: v for k, v in extra_body.items() if k != "temperature"}
                if extra_body:
                    payload["extra_body"] = extra_body
                else:
                    payload.pop("extra_body", None)
        return payload

    def _generate(self: Any, *args: Any, **kwargs: Any) -> Any:
        return retry_request(partial(base_cls._generate, self, *args, **kwargs), partial(_remember_temperature_rejection, self))

    async def _agenerate(self: Any, *args: Any, **kwargs: Any) -> Any:
        return await retry_async_request(partial(base_cls._agenerate, self, *args, **kwargs), partial(_remember_temperature_rejection, self))

    def _stream(self: Any, *args: Any, **kwargs: Any) -> Any:
        stream = partial(base_cls._stream, self, *args, **kwargs)
        yield from retry_stream(stream, partial(_remember_temperature_rejection, self))

    async def _astream(self: Any, *args: Any, **kwargs: Any) -> Any:
        stream = partial(base_cls._astream, self, *args, **kwargs)
        async for chunk in retry_async_stream(stream, partial(_remember_temperature_rejection, self)):
            yield chunk

    safe_cls = type(
        "ChatAnthropicTemperatureSafe",
        (base_cls,),
        {
            "_get_request_payload": _get_request_payload,
            "_generate": _generate,
            "_agenerate": _agenerate,
            "_stream": _stream,
            "_astream": _astream,
        },
    )
    _TEMPERATURE_SAFE_ANTHROPIC_CACHE[base_cls] = safe_cls
    return safe_cls


# Use a positive allowlist because unsupported effort causes a hard 400.
_EFFORT_CAPABLE_ANTHROPIC: tuple[str, ...] = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-mythos-preview",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
)


def _anthropic_supports_effort(model: str) -> bool:
    """Report whether an Anthropic model accepts the effort parameter."""
    name = (model or "").strip().lower()
    return any(name.startswith(prefix) for prefix in _EFFORT_CAPABLE_ANTHROPIC)


def _adapter_accepts_effort(chat_anthropic: type) -> bool:
    """Report whether the installed langchain-anthropic exposes the field."""
    return "reasoning_effort" in getattr(chat_anthropic, "model_fields", {})


def _build_anthropic(
    *,
    model: str,
    temperature: float,
    callbacks: Any = None,
    effort: str = "",
    snapshot: Any,
) -> Any:
    """Build the native Anthropic Messages API adapter."""
    try:
        module = import_module("langchain_anthropic")
        chat_anthropic = getattr(module, "ChatAnthropic")
    except Exception as exc:  # noqa: BLE001 - dependency error with install hint
        raise RuntimeError(
            "Anthropic provider requires langchain-anthropic. Install the optional "
            'extra: pip install "vibe-trading-ai[anthropic]" (or pip install langchain-anthropic).'
        ) from exc

    safe_anthropic = _make_temperature_safe_anthropic(chat_anthropic)
    use_effort = bool(effort) and _anthropic_supports_effort(model) and _adapter_accepts_effort(chat_anthropic)
    # Adaptive thinking accepts only temperature=1, so let the SDK omit temperature.
    client = safe_anthropic(
        model=model,
        max_tokens=snapshot.options.anthropic_max_tokens,
        temperature=None if use_effort else temperature,
        timeout=snapshot.options.timeout_seconds,
        max_retries=snapshot.options.max_retries,
        callbacks=callbacks,
        # The adapter maps this field to output_config.effort.
        **({"reasoning_effort": effort} if use_effort else {}),
        api_key=snapshot.api_key,
        base_url=snapshot.base_url,
        anthropic_proxy=snapshot.environment.get("ANTHROPIC_PROXY"),
    )
    params = getattr(client, "_client_params", None)
    if isinstance(params, dict):
        # auth_token belongs to the SDK client, never the Messages request body.
        params["api_key"] = snapshot.api_key or (None if snapshot.auth_token else "")
        params["auth_token"] = snapshot.auth_token if not snapshot.api_key else None
        headers = dict(
            line.split(":", 1)
            for line in snapshot.environment.get("ANTHROPIC_CUSTOM_HEADERS", "").splitlines()
            if ":" in line
        )
        headers = {**(params.get("default_headers") or {}), **{k.strip(): v.strip() for k, v in headers.items()}}
        sdk_module = import_module("anthropic")
        proxy = snapshot.environment.get("ANTHROPIC_PROXY", "")
        clients = request_guards._build_http_clients(sdk=sdk_module) if snapshot.options.vibe_trading_disable_http_proxy else (
            request_guards._build_http_clients(proxy, sdk=sdk_module) if proxy else None
        )
        if clients:
            # Install transport guards through the SDK clients before first use.
            client._client = sdk_module.Anthropic(**params, http_client=clients[0])
            client._async_client = sdk_module.AsyncAnthropic(**params, http_client=clients[1])
            client._vibe_owned_http_clients = clients
        elif _default_async_client_is_instance_owned("langchain-anthropic", "1.7.12"):
            client._vibe_owned_http_clients = (client._async_client._client,)
        else:
            client._vibe_owned_http_clients = ()
        _guard_provider_redirects(client._client, client._async_client)
        for sdk in (client._client, client._async_client):
            sdk.api_key, sdk.auth_token = params["api_key"], params["auth_token"]
            sdk._custom_headers = dict(headers)
    return client


_PROMPT_CACHE_CONTROL: dict[str, str] = {"type": "ephemeral"}
_DIRECT_ANTHROPIC_LLM_TYPE = "anthropic-chat"


def prompt_cache_messages(messages: list[contracts.ModelMessage]) -> List[Dict[str, Any]]:
    """Return a message list whose leading system string carries a cache breakpoint."""
    if not messages:
        return messages
    first = messages[0]
    if not isinstance(first, dict) or first.get("role") != "system":
        return messages
    content = first.get("content")
    if not isinstance(content, str) or not content:
        return messages
    cached = dict(first)
    cached["content"] = [
        {"type": "text", "text": content, "cache_control": dict(_PROMPT_CACHE_CONTROL)}
    ]
    return [cached, *messages[1:]]
