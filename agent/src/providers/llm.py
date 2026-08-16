"""LLM factory."""

from __future__ import annotations

import logging
import os
from copy import copy
from urllib.parse import urlparse
import re
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from pydantic import PrivateAttr

from src.config.accessor import get_env_config, reset_env_config
from src.providers.capabilities import (
    ProviderCapabilities,
    get_llm_credentials,
    get_provider_capabilities,
)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None  # type: ignore

try:
    from openai import Omit as OpenAIOmit
except ImportError:
    OpenAIOmit = None  # type: ignore

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


def _build_proxy_free_http_clients() -> tuple[Any, Any]:
    """Build sync and async HTTPX clients that ignore proxy environment vars.

    Supplying an explicit transport prevents ``httpx.Client`` from installing
    proxy mounts discovered from HTTP(S)_PROXY.  ``trust_env`` remains enabled
    on the transports so SSL_CERT_FILE and SSL_CERT_DIR still work for private
    certificate authorities.

    Returns:
        A ``(sync_client, async_client)`` pair for the OpenAI SDK.

    Raises:
        RuntimeError: If HTTPX is unavailable while proxy disabling is enabled.
    """
    if httpx is None:
        raise RuntimeError(
            "VIBE_TRADING_DISABLE_HTTP_PROXY requires the httpx package"
        )
    sync_transport = httpx.HTTPTransport(proxy=None, trust_env=True)
    async_transport = httpx.AsyncHTTPTransport(proxy=None, trust_env=True)
    return (
        httpx.Client(transport=sync_transport),
        httpx.AsyncClient(transport=async_transport),
    )


_AMBIENT_OPENAI_HEADER_ENV_VARS = (
    "OPENAI_CUSTOM_HEADERS",
    "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION",
    "OPENAI_PROJECT_ID",
)


class _ResponsesMappingEvent:
    """Attribute view over a raw OpenAI Responses stream event mapping."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        self._values = dict(values)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def model_dump(self, *, exclude_none: bool = False, **_: Any) -> dict[str, Any]:
        """Expose the Pydantic method expected by LangChain's converter."""
        if exclude_none:
            return {
                key: value for key, value in self._values.items() if value is not None
            }
        return dict(self._values)


def _normalize_responses_stream_event(event: Any) -> Any:
    """Adapt raw mapping events to the attribute shape LangChain expects.

    Native OpenAI SDK streams yield typed response event objects. Some
    OpenAI-compatible gateways yield the same wire events as plain dicts;
    langchain-openai's Responses converter accesses ``event.type`` and a few
    nested attributes directly. Preserve typed events unchanged and adapt only
    the mapping form.
    """
    if not isinstance(event, Mapping):
        return event

    values = dict(event)
    for key in ("annotation", "item"):
        nested = values.get(key)
        if isinstance(nested, Mapping):
            values[key] = _ResponsesMappingEvent(nested)
    return _ResponsesMappingEvent(values)


class _ResponsesSyncStream:
    """Proxy a sync Responses stream and normalize each yielded event."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._entered: Any = None

    def __enter__(self) -> "_ResponsesSyncStream":
        self._entered = self._stream.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self._stream.__exit__(*args)

    def __iter__(self) -> Iterator[Any]:
        source = self._entered if self._entered is not None else self._stream
        for event in source:
            yield _normalize_responses_stream_event(event)

    def parse(self, *args: Any, **kwargs: Any) -> "_ResponsesSyncStream":
        """Keep raw-response ``parse()`` streams behind the same proxy."""
        return _ResponsesSyncStream(self._stream.parse(*args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class _ResponsesAsyncStream:
    """Proxy an async Responses stream and normalize each yielded event."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._entered: Any = None

    async def __aenter__(self) -> "_ResponsesAsyncStream":
        self._entered = await self._stream.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> Any:
        return await self._stream.__aexit__(*args)

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Any]:
        source = self._entered if self._entered is not None else self._stream
        async for event in source:
            yield _normalize_responses_stream_event(event)

    def parse(self, *args: Any, **kwargs: Any) -> "_ResponsesAsyncStream":
        """Keep async raw-response ``parse()`` streams behind the proxy."""
        return _ResponsesAsyncStream(self._stream.parse(*args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class _ResponsesSyncResource:
    """Proxy the sync Responses resource without changing non-stream calls."""

    def __init__(self, resource: Any) -> None:
        self._resource = resource

    def create(self, *args: Any, **kwargs: Any) -> Any:
        result = self._resource.create(*args, **kwargs)
        if kwargs.get("stream"):
            return _ResponsesSyncStream(result)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resource, name)


class _ResponsesAsyncResource:
    """Proxy the async Responses resource without changing non-stream calls."""

    def __init__(self, resource: Any) -> None:
        self._resource = resource

    async def create(self, *args: Any, **kwargs: Any) -> Any:
        result = await self._resource.create(*args, **kwargs)
        if kwargs.get("stream"):
            return _ResponsesAsyncStream(result)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resource, name)


class _ResponsesSyncClient:
    """Shallow client proxy used for one sync stream call."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.responses = _ResponsesSyncResource(client.responses)
        raw_response = getattr(client, "with_raw_response", None)
        if raw_response is not None:
            self.with_raw_response = _ResponsesSyncClient(raw_response)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class _ResponsesAsyncClient:
    """Shallow client proxy used for one async stream call."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.responses = _ResponsesAsyncResource(client.responses)
        raw_response = getattr(client, "with_raw_response", None)
        if raw_response is not None:
            self.with_raw_response = _ResponsesAsyncClient(raw_response)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def _openai_custom_header_names(raw: str | None) -> tuple[str, ...]:
    """Return header names parsed by the OpenAI SDK environment format."""
    names: list[str] = []
    for line in (raw or "").split("\n"):
        colon = line.find(":")
        if colon >= 0:
            names.append(line[:colon].strip())
    return tuple(dict.fromkeys(names))


if ChatOpenAI is not None:

    class ChatOpenAIWithReasoning(ChatOpenAI):  # type: ignore[misc,valid-type]
        """ChatOpenAI that preserves provider reasoning across invoke + stream.

        langchain-openai 0.3.x drops non-standard fields in three paths:
          * _convert_dict_to_message — invoke / ainvoke (inbound)
          * _convert_delta_to_message_chunk — stream / astream (inbound)
          * _convert_message_to_dict — request serialization (outbound)
        Moonshot/DeepSeek emit `reasoning_content`; OpenRouter relays as
        `reasoning`. Inbound paths normalize to additional_kwargs["reasoning_content"];
        outbound path re-injects it so strict providers (kimi-k2.6) accept
        multi-turn continuations.
        """

        _vibe_provider: Optional[str] = PrivateAttr(default=None)
        _vibe_api_key: str = PrivateAttr(default="")
        _vibe_ambient_header_names: tuple[str, ...] = PrivateAttr(default=())
        _vibe_has_explicit_authorization: bool = PrivateAttr(default=False)

        def __init__(
            self,
            *args: Any,
            vibe_provider: str | None = None,
            vibe_api_key: str | None = None,
            **kwargs: Any,
        ) -> None:
            """Initialize while retaining the resolved provider name."""
            explicit_headers = kwargs.get("default_headers")
            explicit_names = (
                {str(name) for name in explicit_headers}
                if isinstance(explicit_headers, Mapping)
                else set()
            )
            explicit_names_lower = {name.lower() for name in explicit_names}
            ambient_names = _openai_custom_header_names(
                os.getenv("OPENAI_CUSTOM_HEADERS")  # noqa: env-gate — SDK header isolation
            )
            super().__init__(*args, **kwargs)
            self._vibe_provider = vibe_provider
            self._vibe_api_key = vibe_api_key or ""
            self._vibe_ambient_header_names = tuple(
                name for name in ambient_names if name not in explicit_names
            )
            self._vibe_has_explicit_authorization = (
                "authorization" in explicit_names_lower
            )

        def _provider_scoped_extra_headers(self) -> dict[str, Any]:
            """Remove ambient OpenAI-only headers from named relay requests."""
            provider = (self._vibe_provider or "").strip().lower()
            if not provider or provider == "openai" or OpenAIOmit is None:
                return {}

            overrides: dict[str, Any] = {
                "OpenAI-Organization": OpenAIOmit(),
                "OpenAI-Project": OpenAIOmit(),
            }
            ambient_authorization = False
            for name in self._vibe_ambient_header_names:
                overrides[name] = OpenAIOmit()
                ambient_authorization = (
                    ambient_authorization or name.lower() == "authorization"
                )

            # OPENAI_CUSTOM_HEADERS can override the SDK's normal Bearer header.
            # Remove every captured spelling, then restore the selected provider
            # credential under one canonical name so casing variants cannot
            # produce duplicate Authorization values.
            if (
                ambient_authorization
                and not self._vibe_has_explicit_authorization
                and self._vibe_api_key
            ):
                overrides["Authorization"] = f"Bearer {self._vibe_api_key}"
            return overrides

        def _capabilities(self):
            model = (
                getattr(self, "model_name", None)
                or getattr(self, "model", None)
                or getattr(self, "model_name_", None)
                or ""
            )
            return get_provider_capabilities(self._vibe_provider, str(model))

        @staticmethod
        def _extract_tool_call_thought_signature(tool_call: Any) -> Optional[str]:
            if not isinstance(tool_call, dict):
                return None

            extra_content = tool_call.get("extra_content")
            if isinstance(extra_content, dict):
                google = extra_content.get("google")
                if isinstance(google, dict):
                    value = google.get("thought_signature") or google.get(
                        "thoughtSignature"
                    )
                    if value:
                        return value

            function = tool_call.get("function")
            containers = [tool_call]
            if isinstance(function, dict):
                containers.append(function)
            for container in containers:
                value = container.get("thought_signature") or container.get(
                    "thoughtSignature"
                )
                if value:
                    return value
            return None

        @classmethod
        def _collect_tool_call_thought_signatures(
            cls, tool_calls: Any
        ) -> list[dict[str, Any]]:
            if not isinstance(tool_calls, list):
                return []

            signatures = []
            for fallback_index, tool_call in enumerate(tool_calls):
                signature = cls._extract_tool_call_thought_signature(tool_call)
                if not signature or not isinstance(tool_call, dict):
                    continue

                index = tool_call.get("index")
                entry: dict[str, Any] = {
                    "index": index if isinstance(index, int) else fallback_index,
                    "thought_signature": signature,
                }
                if tool_call.get("id"):
                    entry["id"] = tool_call["id"]
                signatures.append(entry)
            return signatures

        def _capture(self, src: Any, msg: Any) -> None:
            if not isinstance(src, dict):
                return
            caps = self._capabilities()
            if caps.capture_reasoning and (
                value := src.get("reasoning_content") or src.get("reasoning")
            ):
                msg.additional_kwargs["reasoning_content"] = value
            if caps.gemini_thought_signatures and (
                signatures := self._collect_tool_call_thought_signatures(
                    src.get("tool_calls")
                )
            ):
                msg.additional_kwargs["tool_call_thought_signatures"] = signatures

        def _convert_input(self, input: Any) -> Any:  # type: ignore[override]
            """Re-attach Gemini thought signatures dropped by dict->message conversion.

            The AgentLoop replays history as OpenAI-format dicts, stamping the
            signature into ``tool_calls[i].extra_content.google.thought_signature``
            (loop.py ``_attach_tool_call_thought_signatures``). LangChain's
            ``_convert_dict_to_message`` discards ``extra_content`` entirely, so by
            the time ``_get_request_payload`` runs the signature is gone and Gemini
            rejects the next turn with a ``missing thought_signature`` 400.

            ``_convert_input`` is the single chokepoint both ``invoke`` and
            ``stream`` call once at entry, while ``input`` is still raw dicts. Here
            we lift the signatures back onto the converted ``AIMessage`` in the
            same ``additional_kwargs["tool_call_thought_signatures"]`` shape the
            in-memory (#176) path produces, so the existing ``_signature_maps`` /
            ``_inject_tool_call_thought_signatures`` machinery handles both paths
            identically. The ``isinstance(raw, dict)`` guard makes it a no-op when
            re-invoked on already-converted ``BaseMessage`` objects (idempotent).
            """
            prompt_value = super()._convert_input(input)
            if not self._capabilities().gemini_thought_signatures:
                return prompt_value
            if isinstance(input, Sequence) and not isinstance(input, (str, bytes)):
                messages = prompt_value.to_messages()
                if len(messages) == len(input):
                    for raw, msg in zip(input, messages):
                        if (
                            isinstance(raw, dict)
                            and getattr(msg, "type", None) == "ai"
                            and not getattr(msg, "additional_kwargs", {}).get(
                                "tool_call_thought_signatures"
                            )
                        ):
                            sigs = self._collect_tool_call_thought_signatures(
                                raw.get("tool_calls")
                            )
                            if sigs:
                                msg.additional_kwargs[
                                    "tool_call_thought_signatures"
                                ] = sigs
            return prompt_value

        @classmethod
        def _signature_maps(cls, message: Any) -> tuple[dict[str, str], dict[int, str]]:
            by_id: dict[str, str] = {}
            by_index: dict[int, str] = {}
            additional_kwargs = getattr(message, "additional_kwargs", {})

            entries = additional_kwargs.get("tool_call_thought_signatures", [])
            if isinstance(entries, dict):
                entries = [entries]
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    signature = entry.get("thought_signature")
                    if not signature:
                        continue
                    if entry.get("id"):
                        by_id[str(entry["id"])] = signature
                    index = entry.get("index")
                    if isinstance(index, int):
                        by_index[index] = signature

            raw_tool_calls = additional_kwargs.get("tool_calls")
            if isinstance(raw_tool_calls, list):
                for index, tool_call in enumerate(raw_tool_calls):
                    signature = cls._extract_tool_call_thought_signature(tool_call)
                    if not signature or not isinstance(tool_call, dict):
                        continue
                    if tool_call.get("id"):
                        by_id[str(tool_call["id"])] = signature
                    by_index[index] = signature

            return by_id, by_index

        @staticmethod
        def _set_tool_call_thought_signature(tool_call: Any, signature: str) -> None:
            if not isinstance(tool_call, dict):
                return
            extra_content = tool_call.get("extra_content")
            if not isinstance(extra_content, dict):
                extra_content = {}
                tool_call["extra_content"] = extra_content
            google = extra_content.get("google")
            if not isinstance(google, dict):
                google = {}
                extra_content["google"] = google
            google["thought_signature"] = signature

        @classmethod
        def _inject_tool_call_thought_signatures(
            cls, outbound: Any, source_message: Any
        ) -> None:
            if not isinstance(outbound, list):
                return

            by_id, by_index = cls._signature_maps(source_message)
            if not by_id and not by_index:
                return

            for index, tool_call in enumerate(outbound):
                signature = None
                if isinstance(tool_call, dict) and tool_call.get("id"):
                    signature = by_id.get(str(tool_call["id"]))
                signature = signature or by_index.get(index)
                if signature:
                    cls._set_tool_call_thought_signature(tool_call, signature)

        @staticmethod
        def _strip_tool_call_extra_content(outbound: Any) -> None:
            if not isinstance(outbound, list):
                return
            for tool_call in outbound:
                if isinstance(tool_call, dict):
                    tool_call.pop("extra_content", None)

        def _create_chat_result(self, response, generation_info=None):  # type: ignore[override]
            result = super()._create_chat_result(response, generation_info)
            raw = response if isinstance(response, dict) else response.model_dump()
            for gen, choice in zip(result.generations, raw["choices"]):
                self._capture(choice["message"], gen.message)
            return result

        def _stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
            """Route Responses streams through the mapping-compatible adapter."""
            if self._use_responses_api({**kwargs, **self.model_kwargs}):
                cloned = copy(self)
                cloned.root_client = _ResponsesSyncClient(self.root_client)
                return super(ChatOpenAIWithReasoning, cloned)._stream(*args, **kwargs)
            return super()._stream(*args, **kwargs)

        async def _astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            """Async route matching ``_stream`` for Responses compatibility."""
            if self._use_responses_api({**kwargs, **self.model_kwargs}):
                cloned = copy(self)
                cloned.root_async_client = _ResponsesAsyncClient(self.root_async_client)
                async for chunk in super(ChatOpenAIWithReasoning, cloned)._astream(
                    *args, **kwargs
                ):
                    yield chunk
            else:
                async for chunk in super()._astream(*args, **kwargs):
                    yield chunk

        def _convert_chunk_to_generation_chunk(  # type: ignore[override]
            self,
            chunk: dict,
            default_chunk_class: type,
            base_generation_info: Optional[dict],
        ):
            gen = super()._convert_chunk_to_generation_chunk(
                chunk, default_chunk_class, base_generation_info
            )
            if gen is None:
                return None
            choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices")
            if choices:
                self._capture(choices[0]["delta"], gen.message)
            return gen

        def _get_request_payload(  # type: ignore[override]
            self,
            input_: Any,
            *,
            stop: Optional[list[str]] = None,
            **kwargs: Any,
        ) -> dict:
            """Re-inject reasoning_content and normalize assistant content.

            LangChain strips ``reasoning_content`` when serializing AIMessages
            back to OpenAI wire format. Moonshot kimi-k2.6 also rejects
            assistant turns where ``content`` is null or ``reasoning_content``
            is absent, breaking ReAct continuations after a tool call (#39).
            """
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            if "messages" in payload:
                messages = super()._convert_input(input_).to_messages()
                caps = self._capabilities()
                for i, m in enumerate(payload["messages"]):
                    if m.get("role") != "assistant":
                        continue
                    source_message = messages[i]
                    if caps.normalize_assistant_content and m.get("content") is None:
                        m["content"] = ""
                    if caps.send_reasoning_content:
                        m["reasoning_content"] = source_message.additional_kwargs.get(
                            "reasoning_content", ""
                        )
                    else:
                        m.pop("reasoning_content", None)
                    if caps.gemini_thought_signatures:
                        self._inject_tool_call_thought_signatures(
                            m.get("tool_calls"), source_message
                        )
                    else:
                        self._strip_tool_call_extra_content(m.get("tool_calls"))

            scoped_headers = self._provider_scoped_extra_headers()
            if scoped_headers:
                existing_headers = payload.get("extra_headers")
                if isinstance(existing_headers, Mapping):
                    scoped_headers.update(existing_headers)
                payload["extra_headers"] = scoped_headers
            return payload

else:
    ChatOpenAIWithReasoning = None  # type: ignore

AGENT_DIR = Path(__file__).resolve().parents[2]

# .env search order: ~/.vibe-trading/.env → agent/.env → $CWD/.env
_ENV_CANDIDATES = [
    Path.home() / ".vibe-trading" / ".env",
    AGENT_DIR / ".env",
    Path.cwd() / ".env",
]

# Index-aligned with _ENV_CANDIDATES. CWE-209: never log the absolute
# .env path (it leaks the OS username / home / CWD). The label names
# which slot won - the entire P08 R1 signal - using compile-time
# constants only.
_ENV_LABELS = ("~/.vibe-trading/.env", "<AGENT_DIR>/.env", "<CWD>/.env")

# Kimi reasoning models (K-series: kimi-k2*, kimi-k3, …, and the
# kimi-for-coding alias) reject any temperature other than 1 with
# "invalid temperature: only 1 is allowed for this model".
_KIMI_FORCED_TEMPERATURE_RE = re.compile(r"kimi-(k\d+|for-coding)", re.IGNORECASE)

logger = logging.getLogger(__name__)

_dotenv_loaded: bool = False


def _redact_env_source(loaded: Path | None) -> str:
    """Map a resolved `.env` candidate to a stable, leak-free label.

    Returns a symbolic slot label (never the absolute path) so a stale
    or shadowed `.env` stays diagnosable without exposing the OS
    username, home, or CWD (CWE-209). A candidate outside the fixed
    list (e.g. one injected by a test) collapses to a generic
    placeholder rather than echoing a real path.
    """
    if loaded is None:
        return "none (no .env file found)"
    for label, candidate in zip(_ENV_LABELS, _ENV_CANDIDATES):
        if loaded == candidate:
            return label
    return "<.env>"


def _redact_base_url_for_log(raw: str | None) -> str:
    """Return a diagnostic-safe base URL label for logs."""
    if not raw or not raw.strip():
        return "(unset)"

    try:
        parsed = urlsplit(raw.strip())
    except ValueError:
        return "<base-url>"

    if not parsed.scheme or not parsed.hostname:
        return "<base-url>"

    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        host = f"{host}:{port}"

    return f"{parsed.scheme}://{host}"


def _package_version(package: str) -> str:
    """Return an installed package version or a stable missing label."""
    try:
        return version(package)
    except PackageNotFoundError:
        return "not_installed"


def _redact_env_flag(name: str) -> str:
    """Report whether an env var is set without exposing its value."""
    value = os.getenv(name, "")  # noqa: env-gate — diagnostic redaction helper
    return "set" if value else "unset"


def _header_value_diagnostic(value: str) -> dict[str, Any]:
    """Describe a possible HTTP header value without exposing its contents."""
    return {
        "set": bool(value),
        "length": len(value),
        "ascii_only": value.isascii(),
    }


def _credential_env_source(api_key_env: str | None) -> str:
    """Return the env name supplying the selected provider credential."""
    if api_key_env and os.getenv(api_key_env):  # noqa: env-gate — dynamic key source
        return api_key_env
    if os.getenv("OPENAI_API_KEY"):  # noqa: env-gate — compatibility fallback
        return "OPENAI_API_KEY"
    return api_key_env or "built_in"


def _validate_authorization_credential(value: str, *, source: str) -> None:
    """Reject credentials that cannot form a legal ASCII Bearer header."""
    if not value:
        return
    if not value.isascii():
        raise RuntimeError(
            f"{source} contains non-ASCII characters and cannot be sent in an "
            "HTTP Authorization header. Replace it with the raw provider API key "
            "instead of pasted JSON, HTML, or formatted text."
        )
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise RuntimeError(
            f"{source} contains whitespace or control characters and cannot be "
            "sent in an HTTP Authorization header. Replace it with the raw "
            "provider API key."
        )


def _validate_explicit_headers(headers: Mapping[str, str], *, source: str) -> None:
    """Reject explicit provider headers that HTTPX cannot encode safely."""
    for name, value in headers.items():
        if not name.isascii() or not value.isascii():
            raise RuntimeError(
                f"{source} produces a non-ASCII HTTP header ({name!r}). "
                "Use an ASCII-only header value."
            )
        if "\r" in value or "\n" in value:
            raise RuntimeError(
                f"{source} produces an invalid multiline HTTP header ({name!r})."
            )


def _redact_proxy_url(name: str, raw: str | None) -> str:
    """Return a credential-free proxy URL label."""
    if not raw:
        return "unset"
    if name.upper().endswith("NO_PROXY"):
        return "set"
    return _redact_base_url_for_log(raw)


def _deepseek_adapter_mode() -> str:
    """Return the configured DeepSeek adapter mode."""
    mode = get_env_config().llm.vibe_trading_deepseek_adapter.strip().lower()
    aliases = {
        "compat": "openai-compatible",
        "compatible": "openai-compatible",
        "openai": "openai-compatible",
        "openai_compatible": "openai-compatible",
    }
    return aliases.get(mode, mode or "auto")


def _build_native_deepseek(
    *,
    model: str,
    temperature: float,
    callbacks: Any = None,
) -> Any | None:
    """Build the optional native DeepSeek adapter when installed.

    Returns:
        A ChatDeepSeek instance, or ``None`` when the optional package is not
        available.
    """
    try:
        module = import_module("langchain_deepseek")
        chat_deepseek = getattr(module, "ChatDeepSeek")
    except Exception as exc:  # noqa: BLE001 - optional adapter fallback
        logger.info(
            "DeepSeek native adapter unavailable; using OpenAI-compatible path: %s", exc
        )
        return None

    creds = get_llm_credentials("deepseek", model)
    api_key = creds["api_key"]
    base_url = creds["base_url"]
    return chat_deepseek(
        model=model,
        temperature=temperature,
        timeout=get_env_config().llm.timeout_seconds,
        max_retries=get_env_config().llm.max_retries,
        callbacks=callbacks,
        api_key=api_key or None,
        base_url=base_url or None,
    )


def _native_deepseek_adapter_available() -> bool:
    """Return whether the optional native DeepSeek adapter can be imported."""
    try:
        module = import_module("langchain_deepseek")
    except Exception:  # noqa: BLE001 - optional adapter availability probe
        return False
    return callable(getattr(module, "ChatDeepSeek", None))


# Anthropic model names discovered at runtime to reject the `temperature`
# request field. Next-gen Claude models (e.g. claude-opus-5, claude-opus-4-8,
# claude-sonnet-5) return HTTP 400 "`temperature` is deprecated for this model."
# for ANY temperature value, while older models (claude-opus-4-5,
# claude-sonnet-4-5, …) still honor it. Model names are not reliably
# predictable, so membership is populated on first failure and then reused
# process-wide to skip the redundant failed request on subsequent calls.
_ANTHROPIC_TEMPERATURE_UNSUPPORTED: set[str] = set()

# Cache of base ChatAnthropic class -> temperature-safe subclass, so the dynamic
# subclass is built once per resolved base class (keyed to support test doubles).
_TEMPERATURE_SAFE_ANTHROPIC_CACHE: dict[type, type] = {}


def _is_anthropic_temperature_unsupported_error(exc: BaseException) -> bool:
    """Return True when an Anthropic error reports `temperature` as unsupported.

    Matches the model-level deprecation ("`temperature` is deprecated for this
    model.") regardless of the SDK exception type or the temperature value sent.
    """
    message = str(getattr(exc, "message", "") or exc).lower()
    if "temperature" not in message:
        return False
    return (
        "deprecated" in message
        or "not supported" in message
        or "unsupported" in message
        or "not allowed" in message
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
        if isinstance(payload, dict) and self.model in _ANTHROPIC_TEMPERATURE_UNSUPPORTED:
            payload.pop("temperature", None)
        return payload

    def _remember_and_should_retry(self: Any, exc: BaseException) -> bool:
        if _is_anthropic_temperature_unsupported_error(exc):
            if self.model not in _ANTHROPIC_TEMPERATURE_UNSUPPORTED:
                logger.info(
                    "Anthropic model %s rejects `temperature`; retrying without it "
                    "and omitting it for subsequent calls.",
                    self.model,
                )
                _ANTHROPIC_TEMPERATURE_UNSUPPORTED.add(self.model)
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
        # The temperature-unsupported error is raised before the first chunk is
        # produced, so retrying the whole stream cannot duplicate output.
        try:
            yield from base_cls._stream(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - retried or re-raised below
            if _remember_and_should_retry(self, exc):
                yield from base_cls._stream(self, *args, **kwargs)
            else:
                raise

    async def _astream(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            async for chunk in base_cls._astream(self, *args, **kwargs):
                yield chunk
        except Exception as exc:  # noqa: BLE001 - retried or re-raised below
            if _remember_and_should_retry(self, exc):
                async for chunk in base_cls._astream(self, *args, **kwargs):
                    yield chunk
            else:
                raise

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
# providers/capabilities.py is one: an unrecognised model gets nothing, because
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

    ``ChatAnthropic`` is configured with ``extra="ignore"``, so an unknown
    keyword is dropped in silence rather than raising. pyproject allows
    ``langchain-anthropic>=1.3.0``, and ``reasoning_effort`` arrived later --
    without this check, an older install would swallow the value while the
    caller still paid the temperature cost below, which is the worst of both.

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
    use_effort = (
        bool(effort)
        and _anthropic_supports_effort(model)
        and _adapter_accepts_effort(chat_anthropic)
    )
    # Effort makes langchain-anthropic enable adaptive thinking, and the API
    # then rejects any temperature other than 1:
    #   `temperature` may only be set to 1 when thinking is enabled or in
    #   adaptive mode
    # The platform's default is 0.0, so temperature is omitted entirely
    # whenever effort is in play. The temperature-safe wrapper above does not
    # cover this: it handles models that reject `temperature` outright, not
    # this thinking-conditional variant.
    return safe_anthropic(
        model=model,
        max_tokens=get_env_config().llm.anthropic_max_tokens,
        temperature=None if use_effort else temperature,
        timeout=get_env_config().llm.timeout_seconds,
        max_retries=get_env_config().llm.max_retries,
        callbacks=callbacks,
        # Rendered by langchain-anthropic as output_config={'effort': ...}.
        # Without it, Fable 5 and Opus 5 run at the default effort however
        # LANGCHAIN_REASONING_EFFORT is set.
        reasoning_effort=effort if use_effort else None,
        api_key=os.getenv("ANTHROPIC_API_KEY") or None,  # noqa: env-gate — native provider credential
        base_url=(
            os.getenv("ANTHROPIC_BASE_URL")  # noqa: env-gate — native provider endpoint
            or os.getenv("ANTHROPIC_API_URL")  # noqa: env-gate — SDK-compatible alias
            or None
        ),
    )


def _load_env_file(path: Path) -> None:
    """Load a single .env file into os.environ (setdefault, no override)."""
    if load_dotenv is not None:
        load_dotenv(dotenv_path=path, override=False)
    else:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key:
                os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def _ensure_dotenv() -> None:
    """Load `.env` from the first found candidate path."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    loaded = None
    for candidate in _ENV_CANDIDATES:
        if candidate.exists():
            _load_env_file(candidate)
            loaded = candidate
            break
    if loaded is not None:
        reset_env_config()
    _dotenv_loaded = True
    # P08 R1: one-time, behavior-preserving diagnostic so a stale or
    # shadowed .env is observable instead of costing hours. The path is
    # redacted to a symbolic slot label and the API key is never logged.
    logger.info(
        "dotenv resolved from %s | provider=%s model=%s base=%s",
        _redact_env_source(loaded),
        get_env_config().llm.langchain_provider,
        get_env_config().llm.langchain_model_name or "(unset)",
        _redact_base_url_for_log(
            os.getenv("OPENAI_BASE_URL")  # noqa: env-gate — diagnostic display
            or os.getenv("OPENAI_API_BASE")  # noqa: env-gate — diagnostic display
        ),
    )


def _sync_provider_env() -> None:
    """Map provider-specific env vars to OPENAI_* for ChatOpenAI.

    Each entry: provider_name -> (api_key_env, base_url_env).
    Base URLs come from .env; when unset, ``get_llm_credentials`` falls back to
    the provider catalog's ``default_base_url`` (see ``capabilities.py``).
    api_key_env=None means no key required (e.g. Ollama local).
    """
    _ensure_dotenv()
    reset_env_config()
    provider = get_env_config().llm.langchain_provider.lower()

    if provider in {"openai-codex", "openai_codex"}:
        codex_url = get_env_config().llm.openai_codex_base_url
        # SDK-side env setup, not Vibe-Trading config reads
        os.environ["OPENAI_API_BASE"] = codex_url
        os.environ["OPENAI_BASE_URL"] = codex_url
        os.environ.pop("OPENAI_API_KEY", None)
        return

    if provider in {"copilot", "github-copilot"}:
        os.environ.pop("OPENAI_API_BASE", None)
        os.environ.pop("OPENAI_BASE_URL", None)
        os.environ.pop("OPENAI_API_KEY", None)
        return

    creds = get_llm_credentials(provider, get_env_config().llm.langchain_model_name)
    api_key = creds["api_key"]
    base_url = creds["base_url"]

    # SDK-side env setup, not Vibe-Trading config reads
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key
    if base_url:
        os.environ["OPENAI_API_BASE"] = base_url
        os.environ["OPENAI_BASE_URL"] = base_url


def _supports_top_level_reasoning_effort(caps: ProviderCapabilities) -> bool:
    """Report whether a provider accepts a top-level ``reasoning_effort`` field.

    Reads the ``top_level_reasoning_effort`` capability flag, which is a
    positive allowlist: a provider is listed only once a real request to it has
    been observed to succeed. Speaking the OpenAI wire format does not imply
    accepting every OpenAI field, and an endpoint that validates its body
    strictly rejects the unknown key outright — so the default is off and the
    consequence of that default is a no-op, not a failed call.

    Relays that take the effort inside ``extra_body.reasoning`` (OpenRouter,
    Requesty) use that path instead and are excluded here.

    Args:
        caps: Canonical capabilities resolved for the provider and model. Note
            this is the *resolved* capability, so provider ``openai`` with a
            ``deepseek-*`` model arrives here as DeepSeek, and an unrecognised
            provider name arrives as OpenAI — which is why callers must also
            check the base URL before trusting the OpenAI entry.

    Returns:
        True when the provider is on the allowlist and does not use the
        ``extra_body.reasoning`` relay path.
    """
    return caps.top_level_reasoning_effort and not caps.openrouter_reasoning_body


def _openai_label_points_at_openai(caps: ProviderCapabilities) -> bool:
    """Report whether the OpenAI capability is actually talking to OpenAI.

    An unknown ``LANGCHAIN_PROVIDER`` falls back to the OpenAI capabilities, and
    a base-URL override points the OpenAI client at some other gateway (Ollama,
    LiteLLM, a corporate proxy). Those speak the OpenAI wire format but need not
    accept ``reasoning_effort``, so the label alone is not enough to send it.

    Non-OpenAI capabilities are unaffected — they carry their own endpoint.
    """
    if caps.name != "openai":
        return True
    try:
        base_url = (
            get_llm_credentials("openai", get_env_config().llm.langchain_model_name)
            .get("base_url")
            or ""
        ).strip()
    except Exception:  # noqa: BLE001 - a credential lookup must not break the check
        return False
    if not base_url:
        return True
    host = urlparse(base_url if "//" in base_url else f"https://{base_url}").hostname or ""
    return host.lower() in {"api.openai.com", "openai.com"}


def _sends_top_level_reasoning_effort(caps: ProviderCapabilities) -> bool:
    """Combine the allowlist flag with the OpenAI base-URL check."""
    return _supports_top_level_reasoning_effort(caps) and _openai_label_points_at_openai(caps)


def uses_responses_api(
    provider: str,
    configured_responses_api: bool | None,
    deepseek_adapter: str | None = None,
) -> bool:
    """Return whether the configured provider uses ChatOpenAI's Responses route."""
    if configured_responses_api is not True:
        return False
    normalized_provider = provider.strip().lower().replace("_", "-")
    if normalized_provider in {"anthropic", "openai-codex"}:
        return False
    if normalized_provider != "deepseek":
        return True
    adapter = _deepseek_adapter_mode() if deepseek_adapter is None else deepseek_adapter.strip().lower()
    adapter = {
        "compat": "openai-compatible",
        "compatible": "openai-compatible",
        "openai": "openai-compatible",
        "openai_compatible": "openai-compatible",
    }.get(adapter, adapter)
    if adapter == "openai-compatible":
        return True
    return adapter == "auto" and not _native_deepseek_adapter_available()


def provider_diagnostics() -> dict[str, Any]:
    """Build a redacted provider diagnostic snapshot.

    Returns:
        Redacted provider/model/package/env/proxy/capability details.
    """
    _sync_provider_env()
    provider = get_env_config().llm.langchain_provider.strip().lower()
    model = get_env_config().llm.langchain_model_name.strip()
    caps = get_provider_capabilities(provider, model)
    key_env = caps.api_key_env
    creds = get_llm_credentials(provider, model)
    base_url = creds["base_url"]
    credential_source = _credential_env_source(key_env)
    proxy_names = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ]
    package_names = [
        "langchain-openai",
        "langchain-anthropic",
        "langchain-core",
        "langchain",
        "openai",
        "langchain-deepseek",
    ]
    native_package_version = (
        _package_version(caps.native_adapter_package)
        if caps.native_adapter_package
        else None
    )
    adapter_mode = (
        _deepseek_adapter_mode()
        if caps.name == "deepseek"
        else "native"
        if caps.name == "anthropic"
        else "openai-compatible"
    )
    adapter_type = (
        "native"
        if (
            caps.name == "anthropic"
            or (
                caps.name == "deepseek"
                and adapter_mode != "openai-compatible"
                and native_package_version not in {None, "not_installed"}
            )
        )
        else "openai-compatible"
    )
    return {
        "provider": caps.name if provider in {"kimi", "openai_codex"} else provider,
        "model": model,
        "base_url": _redact_base_url_for_log(base_url),
        "api_key": {key_env: _redact_env_flag(key_env)} if key_env else {},
        "http_header_env": {
            "authorization": {
                "source": credential_source,
                **_header_value_diagnostic(creds["api_key"]),
            },
            "ambient_openai": {
                name: _header_value_diagnostic(
                    os.getenv(name, "")  # noqa: env-gate — redacted header diagnostic
                )
                for name in _AMBIENT_OPENAI_HEADER_ENV_VARS
            },
        },
        "env": {
            "LANGCHAIN_PROVIDER": _redact_env_flag("LANGCHAIN_PROVIDER"),
            "LANGCHAIN_MODEL_NAME": _redact_env_flag("LANGCHAIN_MODEL_NAME"),
            "OPENAI_API_KEY": _redact_env_flag("OPENAI_API_KEY"),
            "OPENAI_BASE_URL": _redact_base_url_for_log(
                os.getenv("OPENAI_BASE_URL")  # noqa: env-gate — diagnostic snapshot
            ),
            "OPENAI_API_BASE": _redact_base_url_for_log(
                os.getenv("OPENAI_API_BASE")  # noqa: env-gate — diagnostic snapshot
            ),
        },
        "proxy": {
            name: _redact_proxy_url(
                name, os.getenv(name)  # noqa: env-gate — proxy env iteration
            )
            for name in proxy_names
            if os.getenv(name)  # noqa: env-gate — proxy env filter
        },
        "packages": {name: _package_version(name) for name in package_names},
        "timeout_seconds": get_env_config().llm.timeout_seconds,
        "max_retries": get_env_config().llm.max_retries,
        "reasoning_effort": get_env_config()
        .llm.langchain_reasoning_effort.strip()
        .lower(),
        "adapter": {
            "type": adapter_type,
            "mode": adapter_mode,
            "native_package": caps.native_adapter_package,
            "native_package_version": native_package_version,
        },
        "capabilities": {
            "capture_reasoning": caps.capture_reasoning,
            "send_reasoning_content": caps.send_reasoning_content,
            "gemini_thought_signatures": caps.gemini_thought_signatures,
            "openrouter_reasoning_body": caps.openrouter_reasoning_body,
            "top_level_reasoning_effort": (
                adapter_type == "openai-compatible"
                and _sends_top_level_reasoning_effort(caps)
            ),
        },
    }


def build_llm(*, model_name: Optional[str] = None, callbacks: Any = None) -> Any:
    """Construct the configured LangChain chat model.

    Args:
        model_name: Model name; defaults to LANGCHAIN_MODEL_NAME.
        callbacks: Optional LangChain callbacks.

    Returns:
        Provider-specific LangChain chat model.

    Raises:
        RuntimeError: If langchain-openai is missing or LANGCHAIN_MODEL_NAME is unset.
    """
    _sync_provider_env()
    name = model_name or get_env_config().llm.langchain_model_name.strip()
    if not name:
        raise RuntimeError("LANGCHAIN_MODEL_NAME is not set")
    temperature = get_env_config().llm.langchain_temperature
    provider = get_env_config().llm.langchain_provider.lower()
    caps = get_provider_capabilities(provider, name)
    if provider in {"openai-codex", "openai_codex"}:
        from src.providers.openai_codex import OpenAICodexLLM

        effort = get_env_config().llm.langchain_reasoning_effort.strip().lower()
        return OpenAICodexLLM(
            model=name,
            temperature=temperature,
            timeout=get_env_config().llm.timeout_seconds,
            reasoning_effort=effort or None,
        )

    if provider in {"copilot", "github-copilot"}:
        from src.providers.copilot_auth import CopilotSDKLLM

        return CopilotSDKLLM(
            model=name,
            timeout=get_env_config().llm.timeout_seconds,
        )

    if provider == "anthropic":
        return _build_anthropic(
            model=name,
            temperature=temperature,
            callbacks=callbacks,
            effort=get_env_config().llm.langchain_reasoning_effort.strip().lower(),
        )

    if provider == "deepseek":
        adapter_mode = _deepseek_adapter_mode()
        if adapter_mode != "openai-compatible":
            native_llm = _build_native_deepseek(
                model=name,
                temperature=temperature,
                callbacks=callbacks,
            )
            if native_llm is not None:
                return native_llm
            if adapter_mode == "native":
                raise RuntimeError(
                    "VIBE_TRADING_DEEPSEEK_ADAPTER=native requires langchain-deepseek"
                )

    if ChatOpenAI is None:
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
    effort = get_env_config().llm.langchain_reasoning_effort.strip().lower()
    # Moonshot/DeepSeek official APIs emit reasoning by default and ignore this field.
    configured_responses_api = get_env_config().llm.langchain_use_responses_api
    use_responses_api = uses_responses_api(provider, configured_responses_api)
    creds = get_llm_credentials(provider, name)
    api_key = creds["api_key"]
    _validate_authorization_credential(
        api_key,
        source=_credential_env_source(caps.api_key_env),
    )
    kwargs: dict[str, Any] = {
        "model": name,
        "api_key": api_key or None,
        "base_url": creds["base_url"] or None,
        "temperature": temperature,
        "timeout": get_env_config().llm.timeout_seconds,
        "max_retries": get_env_config().llm.max_retries,
        "callbacks": callbacks,
        "output_version": "responses/v1" if use_responses_api else None,
        "use_responses_api": use_responses_api,
        "reasoning": (
            {"effort": effort}
            if use_responses_api and effort
            else None
        ),
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
                and _sends_top_level_reasoning_effort(caps)
            )
            else None
        ),
        "vibe_provider": provider,
        "vibe_api_key": api_key,
    }
    if caps.default_headers:
        headers = dict(caps.default_headers)
        if caps.name in {"moonshot", "kimi-coding"}:
            custom_ua = get_env_config().llm.moonshot_user_agent.strip()
            if custom_ua:
                headers["User-Agent"] = custom_ua
        _validate_explicit_headers(headers, source=f"{caps.name} provider configuration")
        kwargs["default_headers"] = headers
    if get_env_config().llm.vibe_trading_disable_http_proxy:
        sync_client, async_client = _build_proxy_free_http_clients()
        kwargs["http_client"] = sync_client
        kwargs["http_async_client"] = async_client
    return ChatOpenAIWithReasoning(**kwargs)
