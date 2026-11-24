"""Supervised stream aggregation and empty-stream fallback."""

from __future__ import annotations

import logging
import time
from contextlib import closing
from typing import Any, Callable, Dict, List, Optional

from src.kernel import contracts
from src.providers.adapters.deepseek import _is_possible_dsml_tool_call_prefix
from src.providers.response import ProviderStreamError, _text_content, parse_response
from src.providers.stream_guard import StreamInterrupted, supervised_pulls


logger = logging.getLogger(__name__)


def _is_no_stream_chunk_error(exc: Exception) -> bool:
    """True when a provider accepted the request but streamed zero chunks."""
    return isinstance(exc, ValueError) and "no generation chunks" in str(exc).lower()


def _chunk_model(chunk: Any) -> Optional[str]:
    """Model name one stream chunk reports, before chunks are merged."""
    metadata = getattr(chunk, "response_metadata", {}) or {}
    model = metadata.get("model_name") or metadata.get("model")
    return (str(model).strip() or None) if model is not None else None


def collect_stream(
    adapter: Any,
    prepare: Callable[
        [list[contracts.ModelMessage], list[dict] | None],
        tuple[Any, list[contracts.ModelMessage], dict[str, Any]],
    ],
    messages: list[contracts.ModelMessage],
    tools: Optional[List[Dict[str, Any]]],
    *,
    provider: str,
    model: str,
    secrets: tuple[str, ...],
    on_text_chunk: Optional[Any],
    on_reasoning_chunk: Optional[Any],
    timeout: Optional[int],
    idle_timeout_s: Optional[float],
    should_cancel: Optional[Callable[[], bool]],
    on_waiting_chunk: Optional[Callable[[], None]],
) -> contracts.LLMResponse:
    """Supervise SDK chunks, retain reported usage and return the terminal response."""
    accumulated = None
    cancelled = False
    cancelled_usage = None
    try:
        llm, messages, call_kwargs = prepare(messages, tools)
        config = {"timeout": timeout} if timeout else {}
        pending_text = ""
        possible_dsml_text = True
        started = time.monotonic()
        streamed_model: Optional[str] = None
        try:
            stream_chunks = supervised_pulls(
                llm.stream(messages, config=config, **call_kwargs),
                idle_timeout_s=idle_timeout_s,
                total_timeout_s=timeout,
                should_cancel=should_cancel,
            )
            with closing(stream_chunks):
                for chunk in stream_chunks:
                    if should_cancel and should_cancel():
                        cancelled = True
                        # Keep billed usage from this chunk while discarding text and tool deltas.
                        if getattr(chunk, "usage_metadata", None):
                            usage_chunk = chunk if accumulated is None else accumulated + chunk
                            cancelled_usage = usage_chunk.usage_metadata
                        break
                    accumulated = chunk if accumulated is None else accumulated + chunk
                    if getattr(chunk, "additional_kwargs", {}).get("provider_waiting") is True and on_waiting_chunk:
                        on_waiting_chunk()
                    chunk_text = _text_content(chunk.content)
                    if chunk_text and on_text_chunk:
                        if possible_dsml_text:
                            pending_text += chunk_text
                            if _is_possible_dsml_tool_call_prefix(pending_text):
                                pass
                            else:
                                possible_dsml_text = False
                                on_text_chunk(pending_text)
                                pending_text = ""
                        else:
                            on_text_chunk(chunk_text)
                    reasoning = getattr(chunk, "additional_kwargs", {}).get("reasoning_content")
                    if reasoning and not chunk.content and on_reasoning_chunk:
                        on_reasoning_chunk(reasoning)
                    if streamed_model is None:
                        streamed_model = _chunk_model(chunk)
        except Exception as exc:
            if accumulated is not None or not _is_no_stream_chunk_error(exc):
                raise
        if accumulated is None:
            if cancelled or (should_cancel and should_cancel()):
                return contracts.LLMResponse(content="", usage_metadata=cancelled_usage)
            logger.warning("Provider streamed no chunks; falling back to non-streaming invoke.")
            remaining = timeout - (time.monotonic() - started) if timeout else None
            if remaining is not None and remaining <= 0:
                raise TimeoutError("provider stream stopped: total timeout")

            def invoke():
                yield llm.invoke(messages, config=config, **call_kwargs)

            with closing(supervised_pulls(
                invoke(), idle_timeout_s=idle_timeout_s,
                total_timeout_s=remaining, should_cancel=should_cancel,
            )) as fallback:
                accumulated = next(fallback)
            return parse_response(accumulated, cancelled=bool(should_cancel and should_cancel()))
        # Require an explicit finish reason before releasing Chat Completions output.
        metadata = getattr(accumulated, "response_metadata", {}) or {}
        if (not cancelled and getattr(adapter, "_llm_type", None) in {"openai-chat", "chat-deepseek"}
                and not (metadata.get("finish_reason") or metadata.get("stop_reason")
                         or metadata.get("status") in {"completed", "incomplete", "failed"})):
            raise ConnectionError("Provider stream ended without a terminal finish reason")
        response = parse_response(accumulated, cancelled=cancelled)
        if streamed_model:
            # Keep the per-chunk model name because merging concatenates strings.
            response.response_model = streamed_model
        if cancelled_usage is not None:
            response.usage_metadata = cancelled_usage
        if pending_text and not (response.has_tool_calls and response.content == ""):
            on_text_chunk(pending_text)
        return response
    except StreamInterrupted as stop:
        if stop.reason == "cancelled":
            # Return partial output after a user stop without issuing another request.
            if cancelled_usage is None and getattr(stop.pending, "usage_metadata", None):
                cancelled_usage = stop.pending.usage_metadata
            response = (
                parse_response(accumulated, cancelled=True)
                if accumulated is not None
                else contracts.LLMResponse(content="", tool_calls=[], finish_reason="stop")
            )
            if cancelled_usage is not None:
                response.usage_metadata = cancelled_usage
            return response
        raise ProviderStreamError(
            provider=provider, model=model,
            secrets=secrets,
            original=TimeoutError(f"provider stream stopped: {stop.reason}"),
            usage_metadata=getattr(accumulated, "usage_metadata", None),
        ) from stop
    except Exception as exc:
        raise ProviderStreamError(
            provider=provider, model=model,
            secrets=secrets, original=exc,
            usage_metadata=(getattr(exc, "usage_metadata", None)
                            or getattr(accumulated, "usage_metadata", None)),
        ) from exc
