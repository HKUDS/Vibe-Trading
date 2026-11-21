"""Typed run events and the run result returned by :mod:`vibe_trading`.

The vocabulary is closed: a run yields only the nine event types below. Each
class carries its wire name in ``type`` (``run.started``, ``text.delta`` ...),
named after the nanobot SDK so an embedding application can switch kernels
without renaming its handlers. Internal kernel events that have no entry here
are dropped by the facade, never forwarded raw.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Mapping, Optional, Union

RunStatus = Literal["completed", "failed", "cancelled"]


@dataclass(frozen=True)
class RunResult:
    """Final outcome of one run.

    Attributes:
        session_id: Session the run belongs to.
        attempt_id: Kernel attempt id of the run.
        status: ``completed``, ``failed`` or ``cancelled``.
        text: The assistant reply the session stored for this run. On a
            failure this is the stored failure notice; it is empty when the
            run ended before any reply was written.
        error: Failure reason reported by the kernel, if any.
        provider: LLM provider the run used, when the kernel reported it.
        model: Model that actually answered (the provider's own name when it
            returned one, otherwise the configured model).
        run_dir: Directory holding the run's artifacts and trace, if any.
        usage: Provider-reported token totals from the run's
            ``llm_usage.json`` (``input_tokens``, ``output_tokens``,
            ``total_tokens``, ``calls`` ...). ``None`` when the run recorded
            none; tokens are never estimated.
        elapsed_ms: Wall time the kernel measured for the run, if reported.
    """

    session_id: str
    attempt_id: str
    status: RunStatus
    text: str
    error: Optional[str]
    provider: Optional[str]
    model: Optional[str]
    run_dir: Optional[str]
    usage: Optional[Mapping[str, int]]
    elapsed_ms: Optional[int]


@dataclass(frozen=True)
class RunStarted:
    """The kernel started executing the run."""

    type: ClassVar[str] = "run.started"
    session_id: str
    attempt_id: str


@dataclass(frozen=True)
class TextDelta:
    """A chunk of assistant answer text.

    Attributes:
        text: New text to append. Empty when ``reset`` is set.
        reset: The kernel retracted everything streamed so far in this run
            (a provider retry, or the grounding gate rejecting a draft).
            Discard the text shown so far; :attr:`RunResult.text` is the only
            final answer.
    """

    type: ClassVar[str] = "text.delta"
    session_id: str
    attempt_id: str
    text: str
    reset: bool = False


@dataclass(frozen=True)
class ReasoningDelta:
    """Throttled progress of the model's reasoning stream.

    Attributes:
        text: Rolling tail of the most recent reasoning text (bounded by the
            kernel), not an increment.
        chars: Reasoning characters received so far in this model call.
    """

    type: ClassVar[str] = "reasoning.delta"
    session_id: str
    attempt_id: str
    text: str
    chars: int


@dataclass(frozen=True)
class ToolStarted:
    """The model called a tool.

    Attributes:
        call_id: Provider tool-call id, pairing this with its outcome event.
        tool: Tool name.
        arguments: Redacted, truncated string form of the call arguments.
        blocked: The kernel refused the call without running it; a
            :class:`ToolFailed` follows.
    """

    type: ClassVar[str] = "tool.started"
    session_id: str
    attempt_id: str
    call_id: Optional[str]
    tool: str
    arguments: Mapping[str, str]
    blocked: bool = False


@dataclass(frozen=True)
class ToolCompleted:
    """A tool call returned successfully.

    Attributes:
        call_id: Provider tool-call id.
        tool: Tool name.
        elapsed_ms: Execution time; 0 for a cached or replayed result.
        preview: Short redacted preview of the result.
        cached: The result was served from the run's cache, not re-executed.
    """

    type: ClassVar[str] = "tool.completed"
    session_id: str
    attempt_id: str
    call_id: Optional[str]
    tool: str
    elapsed_ms: int
    preview: str
    cached: bool = False


@dataclass(frozen=True)
class ToolFailed:
    """A tool call returned an error or was refused.

    Attributes:
        call_id: Provider tool-call id.
        tool: Tool name.
        elapsed_ms: Execution time.
        preview: Short redacted preview of the error result.
    """

    type: ClassVar[str] = "tool.failed"
    session_id: str
    attempt_id: str
    call_id: Optional[str]
    tool: str
    elapsed_ms: int
    preview: str


@dataclass(frozen=True)
class RunCompleted:
    """The run finished with an answer. Always the last event."""

    type: ClassVar[str] = "run.completed"
    session_id: str
    attempt_id: str
    result: RunResult


@dataclass(frozen=True)
class RunFailed:
    """The run failed. Always the last event."""

    type: ClassVar[str] = "run.failed"
    session_id: str
    attempt_id: str
    result: RunResult


@dataclass(frozen=True)
class RunCancelled:
    """The run was cancelled. Always the last event."""

    type: ClassVar[str] = "run.cancelled"
    session_id: str
    attempt_id: str
    result: RunResult


Event = Union[
    RunStarted,
    TextDelta,
    ReasoningDelta,
    ToolStarted,
    ToolCompleted,
    ToolFailed,
    RunCompleted,
    RunFailed,
    RunCancelled,
]

TERMINAL_EVENTS = (RunCompleted, RunFailed, RunCancelled)
