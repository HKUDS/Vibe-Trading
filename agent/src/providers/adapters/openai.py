"""OpenAI-compatible chat client with scoped requests and reasoning replay."""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from copy import copy
from typing import Any, Optional

from pydantic import PrivateAttr

from src.providers.adapters.anthropic import (
    _ANTHROPIC_TEMPERATURE_UNSUPPORTED,
    _is_anthropic_temperature_unsupported_error,
)
from src.providers.adapters.common import _default_async_client_is_instance_owned, _endpoint_model
from src.providers.adapters.responses import (
    _RESPONSES_REQUIRED,
    _is_responses_required_error,
    _ResponsesAsyncClient,
    _ResponsesSyncClient,
)
from src.providers.registry import get_provider_capabilities
from src.providers.request_guards import (
    _OPENCODE_SESSION_HEADER,
    _guard_provider_redirects,
    _openai_custom_header_names,
    _targets_opencode,
)
from src.providers.session_context import current_llm_session_id


logger = logging.getLogger(__name__)


try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None  # type: ignore

try:
    from openai import Omit as OpenAIOmit
except ImportError:
    OpenAIOmit = None  # type: ignore


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
            owned_http_clients = tuple(vibe_owned_http_clients or ())
            if (
                vibe_owned_http_clients is None
                and kwargs.get("http_async_client") is None
                and _default_async_client_is_instance_owned("langchain-openai", "1.8.2")
            ):
                # LangChain 1.8.2 stopped caching only the default async client.
                # Its event-loop-bound transport belongs to this adapter, unlike
                # the still-cached synchronous default and explicit user clients.
                owned_http_clients += (self.root_async_client._client,)
            self._vibe_owned_http_clients = owned_http_clients
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

            The AgentRuntime replays history as OpenAI-format dicts, stamping the
            signature into ``tool_calls[i].extra_content.google.thought_signature``
            (providers.messages ``attach_tool_call_thought_signatures``). LangChain's
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
