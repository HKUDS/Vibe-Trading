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
    _default_async_client_is_instance_owned, _endpoint_model, retry_async_stream, retry_stream,
)
from src.providers.request_guards import _guard_provider_redirects


logger = logging.getLogger(__name__)


# Anthropic model names discovered at runtime to reject the `temperature`
# request field. Next-gen Claude models (e.g. claude-opus-5, claude-opus-4-8,
# claude-sonnet-5) return HTTP 400 "`temperature` is deprecated for this model."
# for ANY temperature value, while older models (claude-opus-4-5,
# claude-sonnet-4-5, …) still honor it. Model names are not reliably
# predictable, so membership is populated on first failure and then reused
# process-wide to skip the redundant failed request on subsequent calls.
_ANTHROPIC_TEMPERATURE_UNSUPPORTED: set[tuple[str, str, str]] = set()


# Cache of base ChatAnthropic class -> temperature-safe subclass, so the dynamic
# subclass is built once per resolved base class (keyed to support test doubles).
_TEMPERATURE_SAFE_ANTHROPIC_CACHE: dict[type, type] = {}


def _is_anthropic_temperature_unsupported_error(exc: BaseException) -> bool:
    """Return True when an Anthropic error reports `temperature` as unsupported.

    Matches the model-level deprecation ("`temperature` is deprecated for this
    model.") and the request-validation rejection of the field itself
    ("temperature: Extra inputs are not permitted") regardless of the SDK
    exception type or the temperature value sent.
    """
    message = str(getattr(exc, "message", "") or exc).lower()
    if "temperature" not in message:
        return False
    return (
        "deprecated" in message
        or "not supported" in message
        or "unsupported" in message
        or "not allowed" in message
        # Match the reported field validation, not an unrelated rejection
        # elsewhere in an error that also happens to mention temperature.
        or re.search(r"(?<![\w.])temperature[\"'`]*\s*:\s*extra inputs are not permitted\b", message)
        is not None
    )


def _make_temperature_safe_anthropic(base_cls: type) -> type:
    """Build (and cache) a ChatAnthropic subclass that self-heals temperature.

    Certain Claude models reject the `temperature` field entirely. This subclass
    transparently drops `temperature` from the request and retries once when the
    API reports it as unsupported, remembering the model in
    ``_ANTHROPIC_TEMPERATURE_UNSUPPORTED`` so later requests omit it up front.
    Models that accept `temperature` are unaffected — their configured value
    (e.g. the deterministic 0.0 default) is preserved.

    Built from the class resolved at call time so the optional
    ``langchain-anthropic`` dependency stays lazily imported and test doubles
    still work.
    """
    cached = _TEMPERATURE_SAFE_ANTHROPIC_CACHE.get(base_cls)
    if cached is not None:
        return cached

    def _get_request_payload(self: Any, *args: Any, **kwargs: Any) -> dict:
        payload = base_cls._get_request_payload(self, *args, **kwargs)
        if isinstance(payload, dict) and _endpoint_model(self) in _ANTHROPIC_TEMPERATURE_UNSUPPORTED:
            payload.pop("temperature", None)
            # langchain-anthropic relocates sampling params the installed
            # anthropic SDK (>=1) no longer accepts as named arguments into
            # `extra_body`, which the SDK merges into the request JSON as-is.
            # The API rejects `temperature` from either location.
            extra_body = payload.get("extra_body")
            if isinstance(extra_body, dict) and "temperature" in extra_body:
                extra_body = {k: v for k, v in extra_body.items() if k != "temperature"}
                if extra_body:
                    payload["extra_body"] = extra_body
                else:
                    payload.pop("extra_body", None)
        return payload

    def _remember_and_should_retry(self: Any, exc: BaseException) -> bool:
        if _is_anthropic_temperature_unsupported_error(exc):
            if _endpoint_model(self) not in _ANTHROPIC_TEMPERATURE_UNSUPPORTED:
                logger.info(
                    "Anthropic model %s rejects `temperature`; retrying without it "
                    "and omitting it for subsequent calls.",
                    self.model,
                )
                _ANTHROPIC_TEMPERATURE_UNSUPPORTED.add(_endpoint_model(self))
                return True
        return False

    def _generate(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return base_cls._generate(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - retried or re-raised below
            if _remember_and_should_retry(self, exc):
                return base_cls._generate(self, *args, **kwargs)
            raise

    async def _agenerate(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await base_cls._agenerate(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - retried or re-raised below
            if _remember_and_should_retry(self, exc):
                return await base_cls._agenerate(self, *args, **kwargs)
            raise

    def _stream(self: Any, *args: Any, **kwargs: Any) -> Any:
        stream = partial(base_cls._stream, self, *args, **kwargs)
        yield from retry_stream(stream, partial(_remember_and_should_retry, self))

    async def _astream(self: Any, *args: Any, **kwargs: Any) -> Any:
        stream = partial(base_cls._astream, self, *args, **kwargs)
        async for chunk in retry_async_stream(stream, partial(_remember_and_should_retry, self)):
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


# Effort is not universal across the Anthropic line. Fable 5, Opus 5, Opus
# 4.5-4.8 and Sonnet 5 / 4.6 accept it; Haiku 4.5 and Sonnet 4.5 reject it
# outright with
#   400 invalid_request_error: This model does not support the effort parameter.
#
# That bites hardest in a swarm, where a per-agent ``model_name`` split
# deliberately puts cheap models on the data-gathering seats: one global effort
# setting then kills exactly those workers, and it fails as a hard 400 rather
# than a warning.
#
# A positive allowlist, for the same reason ``top_level_reasoning_effort`` in
# providers/llm_providers.json is one: an unrecognised model gets nothing, because
# the cost of a wrong entry is that every request to it fails, while the cost of
# a missing one is only that the effort setting is inert there.
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
    """Report whether an Anthropic model accepts the effort parameter.

    Args:
        model: The configured Anthropic model name.

    Returns:
        True when the model is on the allowlist above.
    """
    name = (model or "").strip().lower()
    return any(name.startswith(prefix) for prefix in _EFFORT_CAPABLE_ANTHROPIC)


def _adapter_accepts_effort(chat_anthropic: type) -> bool:
    """Report whether the installed langchain-anthropic exposes the field.

    pyproject allows ``langchain-anthropic>=1.3.0``; ``reasoning_effort``
    arrived later. Older adapters can forward unknown kwargs into the API
    payload, so omit this field entirely unless the adapter declares it.

    Args:
        chat_anthropic: The resolved ``ChatAnthropic`` class.

    Returns:
        True when the class declares a ``reasoning_effort`` field.
    """
    return "reasoning_effort" in getattr(chat_anthropic, "model_fields", {})


def _build_anthropic(
    *,
    model: str,
    temperature: float,
    callbacks: Any = None,
    effort: str = "",
    snapshot: Any,
) -> Any:
    """Build the native Anthropic Messages API adapter.

    Uses a temperature-safe subclass so models that deprecate the `temperature`
    field (e.g. claude-opus-5 / claude-sonnet-5) work transparently while models
    that still accept it keep the configured deterministic value.

    `effort` is the configured LANGCHAIN_REASONING_EFFORT, forwarded only to
    models that accept it (see `_anthropic_supports_effort`); an empty string
    means unset.
    """
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
    # Effort makes langchain-anthropic enable adaptive thinking, and the API
    # then rejects any temperature other than 1:
    #   `temperature` may only be set to 1 when thinking is enabled or in
    #   adaptive mode
    # The platform's default is 0.0, so temperature is omitted entirely
    # whenever effort is in play. The temperature-safe wrapper above does not
    # cover this: it handles models that reject `temperature` outright, not
    # this thinking-conditional variant.
    client = safe_anthropic(
        model=model,
        max_tokens=snapshot.options.anthropic_max_tokens,
        temperature=None if use_effort else temperature,
        timeout=snapshot.options.timeout_seconds,
        max_retries=snapshot.options.max_retries,
        callbacks=callbacks,
        # Rendered by langchain-anthropic as output_config={'effort': ...}.
        # Without it, Fable 5 and Opus 5 run at the default effort however
        # LANGCHAIN_REASONING_EFFORT is set.
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
            # ChatAnthropic has no public HTTP-client fields. Populate its cached
            # SDK clients before first use, retaining its normal request params.
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
    """Return a message list whose leading system string carries a cache breakpoint.

    The system prompt is the end of the static prefix (tools render before it),
    so a breakpoint there gives that prefix a guaranteed cache read point even
    when later messages are edited by context compression. Anything other than
    a leading ``{"role": "system", "content": <non-empty str>}`` is returned
    unchanged, and the caller's list is never mutated.
    """
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
