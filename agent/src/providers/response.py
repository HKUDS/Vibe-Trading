"""Normalize provider responses, including incomplete tool calls and retryable failures."""

from __future__ import annotations

import json
from typing import Any, Optional

from src.kernel import contracts
from src.providers.adapters.deepseek import _parse_dsml_tool_calls
from src.providers.content_filter import is_content_filter_triggered
from src.providers.diagnostics import _redact_provider_error
from src.providers.messages import _merge_tool_call_extra_content, _tool_call_thought_signature_maps
from src.providers.request_guards import unwrap_provider_error


def usage_metadata(
    tokens_in: int,
    tokens_out: int,
    *,
    total: int | None = None,
    input_details: dict[str, int] | None = None,
    output_details: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build the usage fields shared by provider responses.

    Args:
        tokens_in: Number of input tokens.
        tokens_out: Number of output tokens.
        total: Reported total, or None to sum the input and output counts.
        input_details: Optional breakdown of input token usage.
        output_details: Optional breakdown of output token usage.

    Returns:
        Usage metadata with the token totals and any nonempty breakdowns.
    """
    metadata: dict[str, Any] = {
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "total_tokens": tokens_in + tokens_out if total is None else total,
    }
    if input_details:
        metadata["input_token_details"] = input_details
    if output_details:
        metadata["output_token_details"] = output_details
    return metadata


def tool_call_chunks(calls: list[dict], *, ensure_ascii: bool = True) -> list[dict]:
    """Serialize complete tool calls as indexed LangChain chunks.

    Args:
        calls: Complete tool calls, each with id, name, and args fields.
        ensure_ascii: Whether to escape non-ASCII characters in serialized arguments.

    Returns:
        One indexed tool-call chunk per call, in input order.
    """
    return [
        {
            "id": call["id"],
            "name": call["name"],
            "args": json.dumps(call["args"], ensure_ascii=ensure_ascii),
            "index": index,
            "type": "tool_call_chunk",
        }
        for index, call in enumerate(calls)
    ]


def _dedupe_finish_reason(raw: str) -> str:
    """Recover the final reason from relays that repeat it on each chunk."""
    return next(
        (m for m in ("tool_calls", "function_call", "content_filter", "length", "stop")
         if raw.endswith(m)),
        raw,
    )


def _text_content(content: Any) -> str:
    """Normalize provider text or content blocks to plain assistant text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif isinstance(getattr(block, "text", None), str):
            parts.append(block.text)
    return "".join(parts)


def reported_model_source(runtime: contracts.LLMRuntimeSnapshot, response_model: Optional[str]) -> str:
    """Name where a reported model id came from.

    Args:
        runtime: Snapshot of the client that made the request.
        response_model: Model the provider response named, if any.

    Returns:
        provider_response or configured for the server's selection, and session_provider_response or
        session for an explicit session selection.
    """
    if runtime.selection == "session":
        return "session_provider_response" if response_model else "session"
    return "provider_response" if response_model else "configured"


def _extract_retry_after_s(original: Exception) -> Optional[float]:
    """Return the provider-suggested Retry-After delay in seconds, if any."""
    response = getattr(original, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = headers.get("Retry-After")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0.0 else None


class ProviderStreamError(RuntimeError):
    """Raised when provider streaming fails before a complete response.

    Args:
        provider: Provider label for the failing request.
        model: Model label for the failing request.
        original: Underlying exception used to derive status, retry timing, and the safe error
            message.
        usage_metadata: Optional measured usage from the failed request.
        secrets: Additional secret values to redact from the message.
    """

    def __init__(self, *, provider: str, model: str, original: Exception, usage_metadata: dict | None = None, secrets: tuple[str, ...] = ()) -> None:
        """Initialize a provider-contextual stream error."""
        self.provider = provider
        self.model = model
        self.original = original
        self.usage_metadata = usage_metadata
        original = unwrap_provider_error(original)
        self.status_code: Optional[int] = getattr(original, "status_code", None)
        self.retry_after_s: Optional[float] = _extract_retry_after_s(original)
        safe_message = _redact_provider_error(str(original))
        for secret in secrets:
            if secret:
                safe_message = safe_message.replace(secret, "[redacted]")
        hint = ""
        lowered = safe_message.lower()
        if any(m in lowered for m in ("<!doctype html", "<html", "__next_error__")):
            # An HTML body usually indicates a website URL in place of the API URL.
            hint = (
                " — the endpoint returned an HTML page instead of a JSON API "
                f"response; verify the {provider} base URL points at the API "
                "root (e.g. the OpenAI-compatible '/v1' path), not the site root"
            )
        super().__init__(
            f"provider_stream_error provider={provider} model={model}: "
            f"{type(original).__name__}: {safe_message}{hint}"
        )

    @property
    def retryable(self) -> bool:
        """Return whether the original failure permits another attempt.

        Returns:
            False for HTTP client errors other than 408 and 429, otherwise True, including when no
            status is available.
        """
        if self.status_code is None:
            return True
        if self.status_code in (408, 429):
            return True
        return not 400 <= self.status_code < 500


def parse_response(ai_message: Any, *, cancelled: bool = False) -> contracts.LLMResponse:
    """Convert a LangChain AIMessage (or AIMessageChunk) to ``contracts.LLMResponse``.

    Args:
        ai_message: Provider AI message or accumulated message chunk.
        cancelled: Whether cancellation should suppress tool calls and allow partial output.

    Returns:
        Normalized response with text, reasoning, available usage, model metadata, and valid tool
        calls.

    Raises:
        ValueError: If a non-cancelled response has invalid, incomplete, non-object, or truncated
            tool arguments.
    """
    usage = getattr(ai_message, "usage_metadata", None)
    # Cast SDK usage objects before persisting them.
    if usage is not None and not isinstance(usage, dict):
        try:
            usage = dict(usage)
        except (TypeError, ValueError):
            usage = None
    additional_kwargs = getattr(ai_message, "additional_kwargs", {}) or {}
    response_metadata = getattr(ai_message, "response_metadata", {}) or {}
    response_model = response_metadata.get("model_name") or response_metadata.get("model")
    if response_model is not None:
        response_model = str(response_model).strip() or None
    thought_signatures_by_id, thought_signatures_by_index = (
        _tool_call_thought_signature_maps(ai_message)
    )
    if not cancelled:
        if getattr(ai_message, "invalid_tool_calls", None):
            raise ValueError("Provider returned invalid tool-call arguments")
        if ai_message.tool_calls:
            # AIMessageChunk repairs partial JSON for previews. Execution
            # requires the original accumulated arguments to be complete.
            for chunk in getattr(ai_message, "tool_call_chunks", ()):
                try:
                    args = json.loads(chunk.get("args") or "{}")
                except (ValueError, TypeError):
                    raise ValueError("Provider returned incomplete tool-call arguments") from None
                if not isinstance(args, dict):
                    raise ValueError("Provider tool-call arguments must be an object")
    raw_tool_calls = additional_kwargs.get("tool_calls") or []
    raw_by_id = {
        raw.get("id"): raw
        for raw in raw_tool_calls
        if isinstance(raw, dict) and raw.get("id")
    }

    native_tool_calls: list[contracts.ToolCallRequest] = []
    for index, tc in enumerate(ai_message.tool_calls):
        extra_content = _merge_tool_call_extra_content(tc, raw_by_id.get(tc["id"]))
        signature = (
            thought_signatures_by_id.get(str(tc["id"]))
            or thought_signatures_by_index.get(index)
            or extra_content.get("thought_signature")
        )
        if signature:
            extra_content.setdefault("thought_signature", signature)
        native_tool_calls.append(
            contracts.ToolCallRequest(
                id=tc["id"],
                name=tc["name"],
                arguments=tc["args"],
                thought_signature=signature,
                extra_content=extra_content,
            )
        )

    content = _text_content(ai_message.content)
    dsml_tool_calls = [] if native_tool_calls else _parse_dsml_tool_calls(content)
    tool_calls = native_tool_calls or dsml_tool_calls

    raw_finish_reason = _dedupe_finish_reason(
        response_metadata.get("finish_reason")
        or response_metadata.get("stop_reason")
        or "stop"
    )
    if response_metadata.get("status") == "incomplete":
        details = response_metadata.get("incomplete_details") or {}
        reason = details.get("reason")
        if reason in contracts.PARTIAL_FINISH_REASONS or reason == "content_filter":
            raw_finish_reason = reason
        elif raw_finish_reason not in contracts.PARTIAL_FINISH_REASONS and not is_content_filter_triggered(raw_finish_reason):
            raw_finish_reason = "incomplete"
    finish_reason = "tool_calls" if dsml_tool_calls or raw_finish_reason == "tool_use" else raw_finish_reason
    if not cancelled and tool_calls and (
        raw_finish_reason in contracts.PARTIAL_FINISH_REASONS
        or response_metadata.get("status") in {"incomplete", "failed"}
    ):
        raise ValueError("Provider truncated a tool call; no tools were executed")
    content_filter_triggered = is_content_filter_triggered(raw_finish_reason)

    return contracts.LLMResponse(
        content="" if dsml_tool_calls else content,
        tool_calls=[] if cancelled else tool_calls,
        reasoning_content=additional_kwargs.get("reasoning_content"),
        finish_reason="stop" if cancelled else finish_reason,
        usage_metadata=usage,
        content_filter_triggered=content_filter_triggered,
        response_model=response_model,
        provider_items=list(additional_kwargs.get("provider_items") or []),
    )
