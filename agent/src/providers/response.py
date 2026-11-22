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


def _dedupe_finish_reason(raw: str) -> str:
    """Relays (OpenRouter) emit finish_reason per chunk; AIMessageChunk.__add__
    concatenates into 'stopstop', 'tool_callstool_calls', etc. Return the
    canonical suffix so ReAct equality checks survive.
    """
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
        ``provider_response`` / ``configured`` for the server's settings, and
        ``session_provider_response`` / ``session`` when the session chose the
        model, so a reader can always tell a session selection apart.
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
    """Raised when provider streaming fails before a complete response."""

    def __init__(self, *, provider: str, model: str, original: Exception, usage_metadata: dict | None = None, secrets: tuple[str, ...] = ()) -> None:
        """Initialize a provider-contextual stream error.

        Args:
            provider: Effective provider name.
            model: Effective model name.
            original: Original exception from the stream path.
            usage_metadata: Usage already reported before stream failure.

        Attributes:
            retry_after_s: Provider-suggested Retry-After delay in seconds,
                extracted from the original exception's response headers when
                present and parseable as a non-negative number; otherwise None.
        """
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
            # An HTML body from a JSON API almost always means the base URL
            # points at a website root, not the API root (a frequent .env
            # misconfiguration for OpenAI-compatible coding-plan gateways).
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
        """Whether a single retry could plausibly succeed.

        Returns:
            False for deterministic client errors (4xx other than 408/429),
            True for everything else — timeouts, rate limits, 5xx, and
            transport errors that carry no HTTP status.
        """
        if self.status_code is None:
            return True
        if self.status_code in (408, 429):
            return True
        return not 400 <= self.status_code < 500


def parse_response(ai_message: Any, *, cancelled: bool = False) -> contracts.LLMResponse:
    """Convert a LangChain AIMessage (or AIMessageChunk) to ``contracts.LLMResponse``.

    Single source for reasoning: ``additional_kwargs["reasoning_content"]``,
    populated by ``ChatOpenAIWithReasoning`` on both stream and non-stream paths.

    ``usage_metadata`` is forwarded as-is from the underlying message so
    downstream cost / billing audit code (e.g. swarm worker token totals)
    can use real provider tokens instead of a character-count heuristic.
    For ``AIMessageChunk`` the metadata accumulates via the ``__add__``
    merge LangChain performs while the response is being streamed; the
    final aggregate carries the same shape as the non-stream path.
    """
    usage = getattr(ai_message, "usage_metadata", None)
    # Some providers / older LangChain versions surface a ``UsageMetadata``
    # TypedDict that doesn't json-serialise without a cast. Normalise to a
    # plain ``dict[str, int]`` so the value can be persisted alongside the
    # rest of the run state without surprises.
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

    raw_finish_reason = (
        ai_message.response_metadata.get("finish_reason")
        or ai_message.response_metadata.get("stop_reason")
        or "stop"
    )
    finish_reason = (
        "tool_calls"
        if dsml_tool_calls
        else "tool_calls"
        if raw_finish_reason == "tool_use"
        else _dedupe_finish_reason(
            raw_finish_reason
        )
    )
    if not cancelled and tool_calls and (
        _dedupe_finish_reason(raw_finish_reason) in {"length", "max_tokens"}
        or response_metadata.get("status") in {"incomplete", "failed"}
    ):
        raise ValueError("Provider truncated a tool call; no tools were executed")
    content_filter_triggered = is_content_filter_triggered(
        raw_finish_reason
    )

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
