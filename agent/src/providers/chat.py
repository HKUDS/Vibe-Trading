"""Synchronous and streaming chat facade and client lifecycle."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional

from src.kernel import contracts
from src.product.tool_policy import ToolPolicy
from src.providers.adapters.anthropic import _DIRECT_ANTHROPIC_LLM_TYPE, _PROMPT_CACHE_CONTROL, prompt_cache_messages
from src.providers.llm import build_llm
from src.providers.request_guards import unwrap_provider_error
from src.providers.response import parse_response
from src.providers.settings import ProviderConfig, resolve_config
from src.providers.stream import collect_stream


logger = logging.getLogger(__name__)


class ChatLLM:
    """LLM chat client with function calling support."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        *,
        policy: ToolPolicy,
        snapshot: ProviderConfig | None = None,
        selection: str = "configured",
    ) -> None:
        """Initialize ChatLLM."""
        self.policy = policy
        self.config = snapshot or resolve_config(model_name=model_name)
        self._llm = build_llm(model_name=model_name, snapshot=self.config, policy=policy)
        self.model_name = model_name or self.config.model
        self.runtime_snapshot = contracts.LLMRuntimeSnapshot(
            provider=self.config.provider or "openai",
            configured_model=self.model_name,
            reasoning_effort=self.config.options.langchain_reasoning_effort.strip().lower(),
            selection=selection,
        )

    def close(self) -> None:
        """Best-effort release of HTTP clients owned by this adapter."""
        for label, client in self._close_candidates():
            close_fn = getattr(client, "aclose", None)
            if not callable(close_fn):
                close_fn = getattr(client, "close", None)
            if not callable(close_fn):
                continue
            try:
                result = close_fn()
                if inspect.isawaitable(result):
                    self._run_or_schedule_close(result, label)
            except Exception:
                logger.debug("ChatLLM.close: failed to close %s", label, exc_info=True)

    async def aclose(self) -> None:
        """Asynchronously release HTTP clients owned by this adapter."""
        for label, client in self._close_candidates():
            close_fn = getattr(client, "aclose", None)
            if not callable(close_fn):
                close_fn = getattr(client, "close", None)
            if not callable(close_fn):
                continue
            try:
                result = close_fn()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.debug("ChatLLM.aclose: failed to close %s", label, exc_info=True)

    def _prompt_cache_request(
        self, messages: list[contracts.ModelMessage]
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Return the messages and call kwargs to send, with cache markers when they apply."""
        if getattr(self._llm, "_llm_type", None) != _DIRECT_ANTHROPIC_LLM_TYPE:
            return messages, {}
        if self.config.options.vibe_trading_anthropic_prompt_cache is not True:
            return messages, {}
        prepared = prompt_cache_messages(messages)
        if prepared is messages:
            return messages, {}
        return prepared, {"cache_control": dict(_PROMPT_CACHE_CONTROL)}

    def _close_candidates(self) -> list[tuple[str, Any]]:
        """Return unique clients this wrapper is responsible for closing."""
        llm = self._llm
        if hasattr(llm, "_vibe_owned_http_clients"):
            candidates = [
                ("owned_http_client", client)
                for client in llm._vibe_owned_http_clients
            ]
        else:
            candidates = [
                (attr, getattr(llm, attr, None))
                for attr in ("root_client", "root_async_client", "client")
            ]

        unique: list[tuple[str, Any]] = []
        seen: set[int] = set()
        for label, client in candidates:
            if client is None or id(client) in seen:
                continue
            seen.add(id(client))
            unique.append((label, client))
        return unique

    @staticmethod
    def _run_or_schedule_close(awaitable: Any, label: str) -> None:
        """Consume an async close from either synchronous or async code."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(awaitable)
            return

        task = loop.create_task(awaitable)

        def _log_failure(done: asyncio.Task[Any]) -> None:
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.debug(
                    "ChatLLM.close: async close failed for %s", label, exc_info=True
                )

        task.add_done_callback(_log_failure)
    def _prepare_call(
        self, messages: list[contracts.ModelMessage], tools: list[dict] | None,
    ) -> tuple[Any, list[contracts.ModelMessage], dict[str, Any]]:
        """Bind offered tools and apply the adapter's request cache markers."""
        available = self.policy.offered_tools(tools) if tools else []
        llm = self._llm.bind_tools(available) if available else self._llm
        prepared, call_kwargs = self._prompt_cache_request(messages)
        return llm, prepared, call_kwargs

    def chat(self, messages: list[contracts.ModelMessage], tools: Optional[List[Dict[str, Any]]] = None, timeout: Optional[int] = None) -> contracts.LLMResponse:
        """Call the LLM synchronously."""
        llm, messages, call_kwargs = self._prepare_call(messages, tools)
        config = {"timeout": timeout} if timeout else {}
        try:
            ai_message = llm.invoke(messages, config=config, **call_kwargs)
        except Exception as exc:
            if (cause := unwrap_provider_error(exc)) is not exc:
                raise cause from None
            raise
        return parse_response(ai_message)

    def stream_chat(
        self,
        messages: list[contracts.ModelMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        on_text_chunk: Optional[Any] = None,
        on_reasoning_chunk: Optional[Any] = None,
        timeout: Optional[int] = None,
        idle_timeout_s: Optional[float] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        on_waiting_chunk: Optional[Callable[[], None]] = None,
    ) -> contracts.LLMResponse:
        """Stream a response and forward deltas to the supplied callbacks."""
        return collect_stream(
            self._llm, self._prepare_call, messages, tools,
            provider=self.runtime_snapshot.provider, model=self.model_name or "(unset)",
            secrets=(self.config.api_key, self.config.auth_token),
            on_text_chunk=on_text_chunk, on_reasoning_chunk=on_reasoning_chunk,
            timeout=timeout, idle_timeout_s=idle_timeout_s,
            should_cancel=should_cancel, on_waiting_chunk=on_waiting_chunk,
        )
