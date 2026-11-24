"""In-memory messages, responses and synchronous turn-loop ports."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Protocol, TypeAlias

from .events import EventSink


# OpenAI-format role/content dictionaries may carry opaque provider metadata.
ModelMessage: TypeAlias = dict[str, Any]


@dataclass
class ToolCallRequest:
    """Carry a tool call and opaque provider metadata for replay."""

    id: str
    name: str
    arguments: Dict[str, Any]
    thought_signature: Optional[str] = None
    extra_content: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMRuntimeSnapshot:
    """Freeze the provider, model and reasoning settings selected by the server or session."""

    provider: str
    configured_model: str
    reasoning_effort: str
    selection: str = "configured"


@dataclass
class LLMResponse:
    """Carry provider-reported usage and identity, with opaque items reserved for verbatim replay."""

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


class Continue(Enum):
    """The host can request one final prose retry at the ordinary limit."""

    NEXT = auto()
    FINAL_ANSWER = auto()


@dataclass(frozen=True)
class Stop:
    reason: str


class CancellationToken(Protocol):
    def is_set(self) -> bool: ...


@dataclass
class LoopContext:
    """Prepared model input and tool definitions for the current request."""

    messages: list[ModelMessage]
    model: LLMRuntimeSnapshot
    tools: list[dict[str, Any]] | None


@dataclass(frozen=True)
class RunLimits:
    max_iterations: int
    partial_finish_reasons: frozenset[str] = frozenset({"length", "max_tokens"})


@dataclass(frozen=True)
class Iteration:
    number: int
    text_only: bool
    final_answer_retry: bool


@dataclass(frozen=True)
class LoopResult:
    messages: list[ModelMessage]
    reason: str
    iterations: int
    usage: dict[str, int]


@dataclass(frozen=True)
class LoopPorts:
    """Bind host operations, including an optional pre-cancellation check that receives the started iteration count."""

    before_iteration: Callable[[LoopContext], Stop | None]
    prepare_request: Callable[[LoopContext, Iteration], Stop | None]
    request: Callable[[LoopContext, EventSink], LLMResponse | Continue | Stop]
    record_partial: Callable[[LLMResponse, str], None]
    after_text: Callable[[LLMResponse], Continue | Stop]
    run_tools: Callable[[LLMResponse], Continue | Stop]
    poll_inputs: Callable[[], None]
    on_cancel: Callable[[], None]
    read_delta: Callable[[], list[ModelMessage]]
    read_usage: Callable[[], dict[str, int]]
    before_cancel_check: Callable[[int], Stop | None] | None = None


@dataclass(frozen=True)
class BoundCall:
    """Bracket an invocation with callbacks that report its start mode and result."""

    start: Callable[[bool], Callable[[], tuple[str, int]]]
    finish: Callable[[str, int], None]
    skip: Callable[[], None]
    parallel: bool
