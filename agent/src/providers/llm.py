"""LLM construction, protocol compatibility and redacted diagnostics.

Construction and wire behavior live together; ChatLLM supplies a settings snapshot.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from copy import copy
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Optional
from urllib.parse import urlparse, urlsplit

from pydantic import PrivateAttr

from src.providers.registry import ProviderCapabilities, get_provider_capabilities
from src.providers.settings import ProviderConfig, resolve_config
from src.providers.session_context import current_llm_session_id

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


def _endpoint_model(client: Any) -> tuple[str, str, str]:
    """Scope learned wire behavior to a protocol, endpoint and model."""
    openai = hasattr(client, "model_name")
    return (
        "openai" if openai else "anthropic",
        str(getattr(client, "openai_api_base" if openai else "anthropic_api_url", "") or "").rstrip("/"),
        str(client.model_name if openai else client.model),
    )


def _build_http_clients(proxy: str | None = None, *, sdk: Any = None) -> tuple[Any, Any]:
    """Build owned HTTPX clients with explicit proxy routing (None means direct).

    Explicit transports prevent ambient proxy mounts while retaining
    SSL_CERT_FILE / SSL_CERT_DIR. Match the SDK's httpx or httpx2 types;
    SDK default-client wrappers may install ambient mounts even with trust_env=False.

    Args:
        proxy: Explicit proxy URL, or None to connect directly.
        sdk: Optional SDK exposing its sync and async HTTP client factories.

    Returns:
        A ``(sync_client, async_client)`` pair.

    Raises:
        RuntimeError: If HTTPX is unavailable.
    """
    if httpx is None:
        raise RuntimeError("Explicit provider transport requires the httpx package")
    http = httpx
    if sdk is not None and not issubclass(sdk.DefaultHttpxClient, httpx.Client):
        http = import_module("httpx2")
    limits = {"limits": sdk.DEFAULT_CONNECTION_LIMITS} if sdk else {}
    sync_transport = http.HTTPTransport(proxy=proxy, trust_env=True, **limits)
    async_transport = http.AsyncHTTPTransport(proxy=proxy, trust_env=True, **limits)
    # Supplying transports bypasses the SDK's ambient proxy discovery while
    # preserving its client defaults (notably Anthropic's redirects).
    sync_cls = sdk.DefaultHttpxClient if sdk else http.Client
    async_cls = sdk.DefaultAsyncHttpxClient if sdk else http.AsyncClient
    return (
        sync_cls(transport=sync_transport),
        async_cls(transport=async_transport),
    )


class ProviderRedirectError(ValueError):
    """A provider redirect would send a request outside its configured origin."""

    status_code = 400


def _check_provider_redirect(response: Any) -> None:
    """Allow redirects only within the same scheme, host and port."""
    if response.has_redirect_location:
        source = response.request.url
        target = source.join(response.headers["location"])
        if (source.scheme, source.host, source.port) != (target.scheme, target.host, target.port):
            raise ProviderRedirectError(
                "Cross-origin provider redirect refused. Configure the final provider base URL explicitly."
            )


async def _check_async_provider_redirect(response: Any) -> None:
    """Apply the same origin check on async HTTP clients."""
    _check_provider_redirect(response)


def _guard_provider_redirects(sync_sdk: Any, async_sdk: Any) -> None:
    """Protect SDK transports without changing their ownership or defaults."""
    # Stateless hooks are safe on LangChain's shared transports; install once.
    for sdk, hook in ((sync_sdk, _check_provider_redirect), (async_sdk, _check_async_provider_redirect)):
        client = getattr(sdk, "_client", None)
        if client is not None and hook not in client.event_hooks["response"]:
            client.event_hooks["response"].append(hook)


def unwrap_provider_error(error: Exception) -> Exception:
    """Preserve a deterministic redirect refusal through SDK connection wrappers."""
    cause = error
    seen = set()
    while cause is not None and id(cause) not in seen:
        if isinstance(cause, ProviderRedirectError):
            return cause
        seen.add(id(cause))
        cause = cause.__cause__
    return error


_OPENCODE_PROVIDER_NAMES = frozenset({"opencode", "opencode-go", "opencode-zen"})
_OPENCODE_SESSION_HEADER = "x-opencode-session"


def _targets_opencode(provider: str | None, base_url: str | None) -> bool:
    """Report whether requests go to the OpenCode relay.

    True for the ``opencode*`` provider names and for any provider whose base
    URL points at ``opencode.ai`` (e.g. ``deepseek`` re-pointed at the Go
    endpoint), so the session header follows the endpoint, not the label.
    """
    normalized = (provider or "").strip().lower().replace("_", "-")
    if normalized in _OPENCODE_PROVIDER_NAMES:
        return True
    raw = (base_url or "").strip()
    if not raw:
        return False
    host = (urlparse(raw if "//" in raw else f"https://{raw}").hostname or "").lower()
    return host == "opencode.ai" or host.endswith(".opencode.ai")


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
            return {key: value for key, value in self._values.items() if value is not None}
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
        _vibe_explicit_twin_headers: dict[str, Any] = PrivateAttr(default_factory=dict)
        _vibe_has_explicit_authorization: bool = PrivateAttr(default=False)
        _vibe_owned_http_clients: tuple[Any, ...] = PrivateAttr(default=())
        _vibe_fallback_session_id: str = PrivateAttr(default="")

        def __init__(
            self,
            *args: Any,
            vibe_provider: str | None = None,
            vibe_api_key: str | None = None,
            vibe_environment: Mapping[str, str] | None = None,
            vibe_owned_http_clients: Sequence[Any] | None = None,
            **kwargs: Any,
        ) -> None:
            """Initialize while retaining the resolved provider name."""
            explicit_headers = kwargs.get("default_headers")
            if vibe_environment is not None and (vibe_provider or "openai") == "openai":
                ambient = dict(
                    line.split(":", 1)
                    for line in vibe_environment.get("OPENAI_CUSTOM_HEADERS", "").splitlines()
                    if ":" in line
                )
                explicit_headers = {**{k.strip(): v.strip() for k, v in ambient.items()}, **(explicit_headers or {})}
                kwargs["default_headers"] = explicit_headers
            explicit_names = (
                {str(name) for name in explicit_headers} if isinstance(explicit_headers, Mapping) else set()
            )
            explicit_names_lower = {name.lower() for name in explicit_names}
            ambient_names = _openai_custom_header_names(
                os.getenv("OPENAI_CUSTOM_HEADERS")  # noqa: env-gate — SDK header isolation
            )
            super().__init__(*args, **kwargs)
            _guard_provider_redirects(self.root_client, self.root_async_client)
            if vibe_environment is not None:
                # SDK constructors may read ambient custom headers even with
                # explicit credentials. Replace only their captured overrides;
                # normal SDK defaults and per-request headers remain intact.
                for client in (self.root_client, self.root_async_client):
                    if client is not None:
                        client._custom_headers = dict(explicit_headers or {})
                        client.project = vibe_environment.get("OPENAI_PROJECT_ID", "")
                        client.organization = vibe_environment.get("OPENAI_ORG_ID") or vibe_environment.get(
                            "OPENAI_ORGANIZATION", ""
                        )
            self._vibe_provider = vibe_provider
            self._vibe_api_key = vibe_api_key or ""
            self._vibe_owned_http_clients = tuple(vibe_owned_http_clients or ())
            # One id per adapter: outside a bound Vibe session (swarm workers,
            # scheduled research, CLI) every request from this adapter still
            # shares a stable conversation identity.
            self._vibe_fallback_session_id = uuid.uuid4().hex
            # Every ambient spelling is omitted per request, and an explicit
            # header sharing its name in another case is put back after the
            # omits (see _provider_scoped_extra_headers). Excluding the twin
            # from the omits instead is right only under openai >= 3.19.2's
            # case-insensitive merge; openai 2.53 (the lock) and 3.19.0 merge
            # with a plain dict and would send the ambient ``user-agent``
            # beside ``User-Agent`` (#1573).
            self._vibe_ambient_header_names = tuple(name for name in ambient_names if name not in explicit_names)
            ambient_names_lower = {name.lower() for name in self._vibe_ambient_header_names}
            self._vibe_explicit_twin_headers = {
                str(name): value
                for name, value in (explicit_headers.items() if isinstance(explicit_headers, Mapping) else ())
                if str(name).lower() in ambient_names_lower
            }
            self._vibe_has_explicit_authorization = "authorization" in explicit_names_lower

        def _opencode_session_headers(self) -> dict[str, str]:
            """Return the ``x-opencode-session`` header for opencode.ai relays.

            OpenCode Go rejects requests without a stable per-conversation id
            (400 ``MissingSessionID``) and uses it for routing and prompt
            caching. The agent loop binds the active Vibe session id via
            ``src.providers.session_context``; the per-adapter fallback keeps
            one conversation stable when no session is bound.
            """
            base_url = getattr(self, "openai_api_base", None)
            if not _targets_opencode(self._vibe_provider, base_url):
                return {}
            session_id = current_llm_session_id() or self._vibe_fallback_session_id
            return {_OPENCODE_SESSION_HEADER: session_id} if session_id else {}

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
                ambient_authorization = ambient_authorization or name.lower() == "authorization"
            # openai >= 3.19.2 applies an omit case-insensitively, so the omit for an
            # ambient ``user-agent`` also took the provider's ``User-Agent``.
            # Inserted after the omits, the explicit value is the one that stays.
            overrides.update(self._vibe_explicit_twin_headers)

            # OPENAI_CUSTOM_HEADERS can override the SDK's normal Bearer header.
            # Remove every captured spelling, then restore the selected provider
            # credential under one canonical name so casing variants cannot
            # produce duplicate Authorization values.
            if ambient_authorization and not self._vibe_has_explicit_authorization and self._vibe_api_key:
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
                    value = google.get("thought_signature") or google.get("thoughtSignature")
                    if value:
                        return value

            function = tool_call.get("function")
            containers = [tool_call]
            if isinstance(function, dict):
                containers.append(function)
            for container in containers:
                value = container.get("thought_signature") or container.get("thoughtSignature")
                if value:
                    return value
            return None

        @classmethod
        def _collect_tool_call_thought_signatures(cls, tool_calls: Any) -> list[dict[str, Any]]:
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
            if caps.capture_reasoning and (value := src.get("reasoning_content") or src.get("reasoning")):
                msg.additional_kwargs["reasoning_content"] = value
            if caps.gemini_thought_signatures and (
                signatures := self._collect_tool_call_thought_signatures(src.get("tool_calls"))
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
                            and not getattr(msg, "additional_kwargs", {}).get("tool_call_thought_signatures")
                        ):
                            sigs = self._collect_tool_call_thought_signatures(raw.get("tool_calls"))
                            if sigs:
                                msg.additional_kwargs["tool_call_thought_signatures"] = sigs
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
        def _inject_tool_call_thought_signatures(cls, outbound: Any, source_message: Any) -> None:
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

        def _generate(self, *args: Any, **kwargs: Any) -> Any:
            try:
                return super()._generate(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - retried or re-raised below
                if not self._recoverable_rejection(exc):
                    raise
                return super()._generate(*args, **kwargs)

        async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
            try:
                return await super()._agenerate(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - retried or re-raised below
                if not self._recoverable_rejection(exc):
                    raise
                return await super()._agenerate(*args, **kwargs)

        def _remember_temperature_unsupported(self, exc: BaseException) -> bool:
            """Record a temperature-unsupported error and report a one-shot retry.

            Mirrors the native Anthropic path for the generic OpenAI-compatible
            branch: next-generation Claude models served through
            ``OPENAI_BASE_URL`` return HTTP 400 when `temperature` is sent
            (issue #1223). The model is remembered in
            ``_ANTHROPIC_TEMPERATURE_UNSUPPORTED`` so later requests omit it up
            front.
            """
            if not _is_anthropic_temperature_unsupported_error(exc):
                return False
            model = str(self.model_name)
            if _endpoint_model(self) not in _ANTHROPIC_TEMPERATURE_UNSUPPORTED:
                logger.info(
                    "Model %s rejects `temperature`; retrying without it and omitting it for subsequent calls.",
                    model,
                )
                _ANTHROPIC_TEMPERATURE_UNSUPPORTED.add(_endpoint_model(self))
                return True
            return False

        def _use_responses_api(self, payload: dict) -> bool:  # type: ignore[override]
            """Route a model whose chat endpoint refused tools to /v1/responses."""
            if _endpoint_model(self) in _RESPONSES_REQUIRED:
                return True
            return super()._use_responses_api(payload)

        def _remember_responses_required(self, exc: BaseException) -> bool:
            """Record a chat-completions refusal naming /v1/responses; report a one-shot retry.

            OpenAI's gpt-5.6-* reject function tools on ``/v1/chat/completions``
            unless ``reasoning_effort`` is 'none', which would run the model
            without its reasoning; the same request on ``/v1/responses`` is
            accepted with the effort under ``reasoning.effort`` (issue #1473).
            The model is remembered in ``_RESPONSES_REQUIRED`` so later requests
            take that route up front. A model that already failed there is not
            retried again.
            """
            if not _is_responses_required_error(exc):
                return False
            model = str(self.model_name)
            if _endpoint_model(self) in _RESPONSES_REQUIRED or self.use_responses_api is True:
                return False
            logger.warning(
                "Model %s refuses function tools on /v1/chat/completions with a "
                "reasoning effort; retrying on /v1/responses and using it for "
                "subsequent calls. Set LANGCHAIN_USE_RESPONSES_API=true to select "
                "it up front.",
                model,
            )
            _RESPONSES_REQUIRED.add(_endpoint_model(self))
            return True

        def _recoverable_rejection(self, exc: BaseException) -> bool:
            """Report whether a failed request should be sent once more.

            Each branch records what the endpoint rejected so the retry, and
            every later request, is shaped differently: without ``temperature``
            (#1223) or on ``/v1/responses`` (#1473).
            """
            return self._remember_temperature_unsupported(exc) or self._remember_responses_required(exc)

        def _stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
            """Route Responses streams through the mapping-compatible adapter."""
            if self._use_responses_api({**kwargs, **self.model_kwargs}):
                cloned = copy(self)
                cloned.root_client = _ResponsesSyncClient(self.root_client)
                inner = super(ChatOpenAIWithReasoning, cloned)._stream(*args, **kwargs)
            else:
                inner = self._stream_with_usage_fallback(*args, **kwargs)
            # The 400 arrives before the first chunk, so restarting the stream
            # cannot duplicate output — but that is a property of the provider,
            # not of this code. Enforce it here instead of assuming it: once a
            # chunk has been emitted the error is re-raised, because replaying
            # the stream would emit those chunks a second time.
            emitted = False
            try:
                for chunk in inner:
                    emitted = True
                    yield chunk
            except Exception as exc:  # noqa: BLE001 - retried or re-raised below
                if emitted or not self._recoverable_rejection(exc):
                    raise
                yield from self._stream(*args, **kwargs)

        def _stream_with_usage_fallback(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
            # stream_usage=True is set at build time so streamed calls report
            # real token counts (issue #1224); an endpoint that rejects
            # stream_options is remembered and retried without it.
            model = str(self.model_name)
            if _endpoint_model(self) in _STREAM_USAGE_UNSUPPORTED:
                yield from super()._stream(*args, stream_usage=False, **kwargs)
                return
            emitted = False
            try:
                for chunk in super()._stream(*args, **kwargs):
                    emitted = True
                    yield chunk
                return
            except Exception as exc:  # noqa: BLE001 - classified below
                if emitted or not _is_stream_usage_unsupported_error(exc):
                    raise
            logger.warning(
                "Endpoint rejects stream usage; streaming without stream_options for %s",
                model,
            )
            _STREAM_USAGE_UNSUPPORTED.add(_endpoint_model(self))
            yield from super()._stream(*args, stream_usage=False, **kwargs)

        async def _astream_with_usage_fallback(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            # stream_usage=True is set at build time so streamed calls report
            # real token counts (issue #1224); an endpoint that rejects
            # stream_options is remembered and retried without it.
            model = str(self.model_name)
            if _endpoint_model(self) in _STREAM_USAGE_UNSUPPORTED:
                async for chunk in super()._astream(*args, stream_usage=False, **kwargs):
                    yield chunk
                return
            emitted = False
            try:
                async for chunk in super()._astream(*args, **kwargs):
                    emitted = True
                    yield chunk
                return
            except Exception as exc:  # noqa: BLE001 - classified below
                if emitted or not _is_stream_usage_unsupported_error(exc):
                    raise
            logger.warning(
                "Endpoint rejects stream usage; streaming without stream_options for %s",
                model,
            )
            _STREAM_USAGE_UNSUPPORTED.add(_endpoint_model(self))
            async for chunk in super()._astream(*args, stream_usage=False, **kwargs):
                yield chunk

        async def _astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            """Async route matching ``_stream`` for Responses compatibility."""
            if self._use_responses_api({**kwargs, **self.model_kwargs}):
                cloned = copy(self)
                cloned.root_async_client = _ResponsesAsyncClient(self.root_async_client)
                inner = super(ChatOpenAIWithReasoning, cloned)._astream(*args, **kwargs)
            else:
                inner = self._astream_with_usage_fallback(*args, **kwargs)
            # The 400 arrives before the first chunk, so restarting the stream
            # cannot duplicate output — but that is a property of the provider,
            # not of this code. Enforce it here instead of assuming it: once a
            # chunk has been emitted the error is re-raised, because replaying
            # the stream would emit those chunks a second time.
            emitted = False
            try:
                async for chunk in inner:
                    emitted = True
                    yield chunk
            except Exception as exc:  # noqa: BLE001 - retried or re-raised below
                if emitted or not self._recoverable_rejection(exc):
                    raise
                async for chunk in self._astream(*args, **kwargs):
                    yield chunk

        def _convert_chunk_to_generation_chunk(  # type: ignore[override]
            self,
            chunk: dict,
            default_chunk_class: type,
            base_generation_info: Optional[dict],
        ):
            gen = super()._convert_chunk_to_generation_chunk(chunk, default_chunk_class, base_generation_info)
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
            # LangChain rewrites max_tokens to OpenAI's newer spelling.
            # DeepSeek documents max_tokens and silently ignores the other
            # field, leaving its much larger thinking-mode default in force.
            if "messages" in payload and self._capabilities().name == "deepseek":
                if "max_completion_tokens" in payload:
                    payload["max_tokens"] = payload.pop("max_completion_tokens")
            # Models that rejected `temperature` before omit it up front (#1223).
            if _endpoint_model(self) in _ANTHROPIC_TEMPERATURE_UNSUPPORTED:
                payload.pop("temperature", None)
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
                        m["reasoning_content"] = source_message.additional_kwargs.get("reasoning_content", "")
                    else:
                        m.pop("reasoning_content", None)
                    if caps.gemini_thought_signatures:
                        self._inject_tool_call_thought_signatures(m.get("tool_calls"), source_message)
                    else:
                        self._strip_tool_call_extra_content(m.get("tool_calls"))

            scoped_headers = self._provider_scoped_extra_headers()
            if scoped_headers:
                existing_headers = payload.get("extra_headers")
                if isinstance(existing_headers, Mapping):
                    scoped_headers.update(existing_headers)
                payload["extra_headers"] = scoped_headers
            session_headers = self._opencode_session_headers()
            if session_headers:
                existing_headers = payload.get("extra_headers")
                merged: dict[str, Any] = dict(existing_headers) if isinstance(existing_headers, Mapping) else {}
                present = {str(name).lower() for name in merged}
                for name, value in session_headers.items():
                    if name.lower() not in present:
                        merged[name] = value
                payload["extra_headers"] = merged
            return payload

else:
    ChatOpenAIWithReasoning = None  # type: ignore

# Kimi reasoning models (K-series: kimi-k2*, kimi-k3, …, and the
# kimi-for-coding alias) reject any temperature other than 1 with
# "invalid temperature: only 1 is allowed for this model".
_KIMI_FORCED_TEMPERATURE_RE = re.compile(r"kimi-(k\d+|for-coding)", re.IGNORECASE)

logger = logging.getLogger(__name__)


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
            raise RuntimeError(f"{source} produces a non-ASCII HTTP header ({name!r}). Use an ASCII-only header value.")
        if "\r" in value or "\n" in value:
            raise RuntimeError(f"{source} produces an invalid multiline HTTP header ({name!r}).")


def _deepseek_adapter_mode(value: str = "auto") -> str:
    """Return the configured DeepSeek adapter mode."""
    mode = value.strip().lower()
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
    snapshot: Any,
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
        logger.info("DeepSeek native adapter unavailable; using OpenAI-compatible path: %s", exc)
        return None

    api_key, base_url = snapshot.api_key, snapshot.base_url
    if not api_key:
        raise RuntimeError("Set DEEPSEEK_API_KEY (or legacy OPENAI_API_KEY) before using the native DeepSeek adapter")
    output_limit = snapshot.options.langchain_max_tokens
    sdk_module = import_module("openai")
    proxy = snapshot.environment.get("OPENAI_PROXY", "")
    clients = _build_http_clients(sdk=sdk_module) if snapshot.options.vibe_trading_disable_http_proxy else (
        _build_http_clients(proxy, sdk=sdk_module) if proxy else None
    )
    client = chat_deepseek(
        model=model,
        temperature=temperature,
        timeout=snapshot.options.timeout_seconds,
        max_retries=snapshot.options.max_retries,
        callbacks=callbacks,
        api_key=api_key,
        base_url=base_url,
        openai_proxy="" if clients else proxy,
        **({"http_client": clients[0], "http_async_client": clients[1]} if clients else {}),
        **({"max_tokens": output_limit} if output_limit is not None else {}),
    )
    # Unlike ChatOpenAI, ChatDeepSeek constructs per-instance SDK clients.
    client._vibe_owned_http_clients = clients or (client.root_client, client.root_async_client)
    _guard_provider_redirects(client.root_client, client.root_async_client)
    for sdk in (getattr(client, "root_client", None), getattr(client, "root_async_client", None)):
        if sdk is not None:
            sdk._custom_headers = {}
            sdk.organization = sdk.project = None
    return client


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
_ANTHROPIC_TEMPERATURE_UNSUPPORTED: set[tuple[str, str, str]] = set()

# Endpoints discovered at runtime to reject the `stream_options` request
# field. OpenAI-compatible gateways vary on include_usage support; membership
# is populated on first failure and reused process-wide to skip the redundant
# failed request on later calls (issue #1224).
_STREAM_USAGE_UNSUPPORTED: set[tuple[str, str, str]] = set()


def _is_stream_usage_unsupported_error(exc: BaseException) -> bool:
    """Return True when an endpoint rejects the `stream_options` field.

    Matches request-validation rejections of `stream_options`/`include_usage`
    regardless of the SDK exception type.
    """
    message = str(getattr(exc, "message", "") or exc).lower()
    if "stream_options" not in message and "include_usage" not in message:
        return False
    return (
        "unsupported" in message
        or "not supported" in message
        or "unknown" in message
        or "unrecognized" in message
        or "invalid" in message
        or "not valid" in message
        or "not a valid" in message
        or "not allowed" in message
    )


# Models whose Chat Completions endpoint refused function tools and named
# /v1/responses as the way out (issue #1473). OpenAI's gpt-5.6-* answer HTTP 400
# "Function tools with reasoning_effort are not supported for <model> in
# /v1/chat/completions. To use function tools, use /v1/responses or set
# reasoning_effort to 'none'" whenever the request carries tools and the effort
# is anything but 'none' -- the model's own default when none is configured
# included. Setting 'none' would run the model without its reasoning, so the
# request is retried on /v1/responses instead, where the effort travels as
# ``reasoning.effort``. Membership is populated on that first refusal and reused
# process-wide so later calls skip the failed request.
_RESPONSES_REQUIRED: set[tuple[str, str, str]] = set()


def _is_responses_required_error(exc: BaseException) -> bool:
    """Return True when an endpoint refused tools and pointed at /v1/responses.

    Matches the endpoint's own instruction, not a model name: the message has
    to name ``reasoning_effort``, say it is not supported, and offer
    ``/v1/responses``. A gateway that merely rejects ``reasoning_effort`` as an
    unknown field does not match, because nothing says its Responses route
    would fare better.
    """
    message = str(getattr(exc, "message", "") or exc).lower()
    if "reasoning_effort" not in message or "/v1/responses" not in message:
        return False
    return "not supported" in message or "unsupported" in message


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
    return "deprecated" in message or "not supported" in message or "unsupported" in message or "not allowed" in message


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
        emitted = False
        try:
            for chunk in base_cls._stream(self, *args, **kwargs):
                emitted = True
                yield chunk
        except Exception as exc:  # noqa: BLE001 - retried or re-raised below
            if not emitted and _remember_and_should_retry(self, exc):
                yield from base_cls._stream(self, *args, **kwargs)
            else:
                raise

    async def _astream(self: Any, *args: Any, **kwargs: Any) -> Any:
        emitted = False
        try:
            async for chunk in base_cls._astream(self, *args, **kwargs):
                emitted = True
                yield chunk
        except Exception as exc:  # noqa: BLE001 - retried or re-raised below
            if not emitted and _remember_and_should_retry(self, exc):
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
        clients = _build_http_clients(sdk=sdk_module) if snapshot.options.vibe_trading_disable_http_proxy else (
            _build_http_clients(proxy, sdk=sdk_module) if proxy else None
        )
        if clients:
            # ChatAnthropic has no public HTTP-client fields. Populate its cached
            # SDK clients before first use, retaining its normal request params.
            client._client = sdk_module.Anthropic(**params, http_client=clients[0])
            client._async_client = sdk_module.AsyncAnthropic(**params, http_client=clients[1])
        client._vibe_owned_http_clients = clients or ()
        _guard_provider_redirects(client._client, client._async_client)
        for sdk in (client._client, client._async_client):
            sdk.api_key, sdk.auth_token = params["api_key"], params["auth_token"]
            sdk._custom_headers = dict(headers)
    return client


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
    if deepseek_adapter is None:
        from src.config.accessor import get_env_value

        deepseek_adapter = get_env_value("VIBE_TRADING_DEEPSEEK_ADAPTER", "auto")
    adapter = _deepseek_adapter_mode(deepseek_adapter)
    if adapter == "openai-compatible":
        return True
    return adapter == "auto" and not _native_deepseek_adapter_available()


def build_llm(*, model_name: str | None = None, callbacks: Any = None, snapshot: ProviderConfig | None = None) -> Any:
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
            model=name,
            timeout=options.timeout_seconds,
            reasoning_effort=options.langchain_reasoning_effort.strip().lower(),
            environment=dict(snapshot.environment),
        )

    if snapshot.backend == "anthropic":
        return _build_anthropic(
            model=name,
            temperature=temperature,
            callbacks=callbacks,
            snapshot=snapshot,
            effort=options.langchain_reasoning_effort.strip().lower(),
        )

    if snapshot.backend == "deepseek":
        adapter_mode = _deepseek_adapter_mode(options.vibe_trading_deepseek_adapter)
        if adapter_mode != "openai-compatible":
            native_llm = _build_native_deepseek(
                model=name,
                temperature=temperature,
                callbacks=callbacks,
                snapshot=snapshot,
            )
            if native_llm is not None:
                return native_llm
            if adapter_mode == "native":
                raise RuntimeError("VIBE_TRADING_DEEPSEEK_ADAPTER=native requires langchain-deepseek")

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
        clients = _build_http_clients()
    elif explicit_proxy:
        clients = _build_http_clients(explicit_proxy)
    if clients:
        kwargs["http_client"], kwargs["http_async_client"] = clients
        kwargs["vibe_owned_http_clients"] = clients
        kwargs["openai_proxy"] = ""
    return ChatOpenAIWithReasoning(**kwargs)


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


def _redact_env_flag(name: str, environment) -> str:
    """Report whether an env var is set without exposing its value."""
    value = environment.get(name, "")
    return "set" if value else "unset"


def _header_value_diagnostic(value: str) -> dict[str, Any]:
    """Describe a possible HTTP header value without exposing its contents."""
    return {
        "set": bool(value),
        "length": len(value),
        "ascii_only": value.isascii(),
    }


def _redact_proxy_url(name: str, raw: str | None) -> str:
    """Return a credential-free proxy URL label."""
    if not raw:
        return "unset"
    if name.upper().endswith("NO_PROXY"):
        return "set"
    return _redact_base_url_for_log(raw)


def provider_diagnostics() -> dict[str, Any]:
    """Build a redacted provider diagnostic snapshot.

    Returns:
        Redacted provider/model/package/env/proxy/capability details.
    """
    snapshot = resolve_config()
    environment = snapshot.environment
    provider, model = snapshot.provider, snapshot.model
    options = snapshot.options
    caps = get_provider_capabilities(provider, model)
    key_env = caps.api_key_env
    base_url = snapshot.base_url
    credential_source = key_env if key_env and snapshot.environment.get(key_env) else "OPENAI_API_KEY"
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
    native_package_version = _package_version(caps.native_adapter_package) if caps.native_adapter_package else None
    adapter_mode = adapter_type = "openai-compatible"
    if snapshot.backend == "anthropic":
        adapter_mode = adapter_type = "native"
    elif snapshot.backend == "deepseek":
        adapter_mode = _deepseek_adapter_mode(options.vibe_trading_deepseek_adapter)
        if adapter_mode != "openai-compatible" and native_package_version not in {None, "not_installed"}:
            adapter_type = "native"
    from src.providers.tool_policy import policy_status

    return {
        "provider": caps.name if provider in {"kimi", "openai_codex"} else provider,
        "model": model,
        "backend": snapshot.backend,
        "base_url": _redact_base_url_for_log(base_url),
        "api_key": {key_env: _redact_env_flag(key_env, environment)} if key_env else {},
        "http_header_env": {
            "authorization": {
                "source": credential_source,
                **_header_value_diagnostic(snapshot.api_key),
            },
            "ambient_openai": {
                name: _header_value_diagnostic(environment.get(name, ""))
                for name in _AMBIENT_OPENAI_HEADER_ENV_VARS
            },
        },
        "env": {
            "LANGCHAIN_PROVIDER": _redact_env_flag("LANGCHAIN_PROVIDER", environment),
            "LANGCHAIN_MODEL_NAME": _redact_env_flag("LANGCHAIN_MODEL_NAME", environment),
            "OPENAI_API_KEY": _redact_env_flag("OPENAI_API_KEY", environment),
            "OPENAI_BASE_URL": _redact_base_url_for_log(environment.get("OPENAI_BASE_URL")),
            "OPENAI_API_BASE": _redact_base_url_for_log(environment.get("OPENAI_API_BASE")),
        },
        "proxy": {
            name: _redact_proxy_url(
                name,
                environment.get(name),
            )
            for name in proxy_names
            if environment.get(name)
        },
        "packages": {name: _package_version(name) for name in package_names},
        "timeout_seconds": options.timeout_seconds,
        "max_retries": options.max_retries,
        "tool_policy": policy_status(),
        "reasoning_effort": options.langchain_reasoning_effort.strip().lower(),
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
                and _sends_top_level_reasoning_effort(caps, model, snapshot.base_url)
            ),
        },
    }
