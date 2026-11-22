"""In-memory messages, responses and synchronous turn-loop ports."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, Generic, List, Optional, Protocol, TypeAlias, TypeVar


# OpenAI-format role/content dictionaries may carry opaque provider metadata.
ModelMessage: TypeAlias = dict[str, Any]


@dataclass
class ToolCallRequest:
    """Tool call request returned by the LLM.

    Attributes:
        id: Tool call ID (used to match tool_result messages).
        name: Tool name.
        arguments: Tool argument dict.
        thought_signature: Gemini thinking-model signature to echo on the next turn.
        extra_content: Provider-specific tool-call metadata that must be
            replayed with the assistant turn, such as Gemini thought signatures.
    """

    id: str
    name: str
    arguments: Dict[str, Any]
    thought_signature: Optional[str] = None
    extra_content: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMRuntimeSnapshot:
    """Immutable identity of the model configuration used by one ChatLLM.

    Attributes:
        provider: Provider the client sends to.
        configured_model: Model the client asks for.
        reasoning_effort: Effort level the client sends, or "" when unset.
        selection: Who chose the model: ``"configured"`` for the server's
            settings, ``"session"`` for a selection stored on the session.
    """

    provider: str
    configured_model: str
    reasoning_effort: str
    selection: str = "configured"


@dataclass
class LLMResponse:
    """LLM response.

    Attributes:
        content: Text content (final answer or thinking text).
        tool_calls: List of tool call requests.
        reasoning_content: Optional thinking trace surfaced by reasoning models.
        finish_reason: Finish reason string.
        usage_metadata: Real token counts reported by the provider, when
            available. Mirrors LangChain's ``AIMessage.usage_metadata`` —
            ``{"input_tokens": int, "output_tokens": int, "total_tokens": int}``.
            ``None`` if the provider did not return usage information; callers
            should fall back to a heuristic in that case.
        content_filter_triggered: ``True`` when the provider blocked the
            response via content moderation (e.g. DashScope/Qwen content
            moderation filter, ``finish_reason == "content_filter"``).
        response_model: Model identifier reported by the provider response,
            when available. This is authoritative runtime metadata and must
            not be inferred from the model's natural-language self-report.
        provider_items: Opaque output items the provider needs back verbatim
            on the next request of the same turn chain (the Codex backend's
            encrypted reasoning items). Never shown, never summarised.
    """

    content: Optional[str] = None
    tool_calls: List[ToolCallRequest] = field(default_factory=list)
    reasoning_content: Optional[str] = None
    finish_reason: str = "stop"
    usage_metadata: Optional[Dict[str, int]] = None
    content_filter_triggered: bool = False
    response_model: Optional[str] = None
    provider_items: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        """Return True if the response contains tool calls."""
        return len(self.tool_calls) > 0


class LoopDecision(Enum):
    """Disposition of a request or response handled by a bound port."""

    CONTINUE = auto()
    STOP = auto()


class LoopContext(Protocol):
    """Scheduling state shared with the caller for one run."""

    iteration: int
    final_answer_retry: bool
    final_answer_retry_pending: bool


ContextT = TypeVar("ContextT", bound=LoopContext)


@dataclass(frozen=True)
class LoopPorts(Generic[ContextT]):
    """Host operations invoked by the scheduler at the existing turn boundaries."""

    prepare_iteration: Callable[[ContextT], LoopDecision]
    request: Callable[[ContextT], LLMResponse | LoopDecision]
    record_partial: Callable[[ContextT, LLMResponse, str], None]
    after_text: Callable[[ContextT, LLMResponse], LoopDecision]
    run_tools: Callable[[ContextT, LLMResponse], LoopDecision]


@dataclass(frozen=True)
class BoundCall:
    """Publish a call's start, invoke the bound tool, then publish its result.

    The start callback receives whether this call will run in parallel.
    """

    start: Callable[[bool], Callable[[], tuple[str, int]]]
    finish: Callable[[str, int], None]
    skip: Callable[[], None]
    parallel: bool
