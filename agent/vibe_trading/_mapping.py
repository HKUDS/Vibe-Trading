"""The one table from kernel event names to public :mod:`vibe_trading.events`.

Every translation the facade performs lives in :data:`EVENT_TABLE`. To point
the facade at a different kernel event stream, replace the keys and builders
here; nothing else in the package reads kernel event names.

Sources of the shapes read below:

* ``attempt.*`` — ``SessionService._run_attempt`` (terminal names come from
  its ``_TERMINAL_EVENTS``; the exception branch emits ``attempt.failed``
  with only ``attempt_id`` and ``error``).
* ``text_delta`` / ``stream_reset`` / ``reasoning_delta`` —
  ``src.agent.loop_streaming.TurnStream`` and ``AgentLoop``.
* ``tool_call`` / ``tool_result`` — ``src.agent.tool_lifecycle``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

from vibe_trading.events import (
    Event,
    ReasoningDelta,
    RunCancelled,
    RunCompleted,
    RunFailed,
    RunResult,
    RunStarted,
    TextDelta,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)

#: Run artifact holding provider-reported usage (``src.agent.llm_usage``).
_USAGE_ARTIFACT = "llm_usage.json"

Builder = Callable[[str, str, Mapping[str, Any]], Optional[Event]]


def _optional_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _read_usage(run_dir: Optional[str]) -> Optional[Mapping[str, int]]:
    """Return the run's persisted usage totals, or None when it has none.

    Args:
        run_dir: Run directory the kernel reported.

    Returns:
        Read-only integer totals, or None when the artifact is missing,
        unreadable or reports no call.
    """
    if not run_dir:
        return None
    try:
        summary = json.loads((Path(run_dir) / _USAGE_ARTIFACT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    totals = summary.get("totals") if isinstance(summary, dict) else None
    if not isinstance(totals, dict):
        return None
    clean = {
        key: int(value)
        for key, value in totals.items()
        if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool)
    }
    if not clean.get("calls"):
        return None
    return MappingProxyType(clean)


def _run_started(session_id: str, attempt_id: str, data: Mapping[str, Any]) -> Event:
    return RunStarted(session_id=session_id, attempt_id=attempt_id)


def _text_delta(session_id: str, attempt_id: str, data: Mapping[str, Any]) -> Optional[Event]:
    delta = data.get("delta")
    if not isinstance(delta, str) or not delta:
        return None
    return TextDelta(session_id=session_id, attempt_id=attempt_id, text=delta)


def _text_reset(session_id: str, attempt_id: str, data: Mapping[str, Any]) -> Event:
    return TextDelta(session_id=session_id, attempt_id=attempt_id, text="", reset=True)


def _reasoning_delta(session_id: str, attempt_id: str, data: Mapping[str, Any]) -> Event:
    tail = data.get("tail")
    return ReasoningDelta(
        session_id=session_id,
        attempt_id=attempt_id,
        text=tail if isinstance(tail, str) else "",
        chars=_non_negative_int(data.get("chars")),
    )


def _tool_started(session_id: str, attempt_id: str, data: Mapping[str, Any]) -> Optional[Event]:
    tool = _optional_str(data.get("tool"))
    if tool is None:
        return None
    raw_arguments = data.get("arguments")
    arguments = (
        {str(key): str(value) for key, value in raw_arguments.items()}
        if isinstance(raw_arguments, dict)
        else {}
    )
    return ToolStarted(
        session_id=session_id,
        attempt_id=attempt_id,
        call_id=_optional_str(data.get("call_id")),
        tool=tool,
        arguments=MappingProxyType(arguments),
        blocked=data.get("blocked") is True,
    )


def _tool_finished(session_id: str, attempt_id: str, data: Mapping[str, Any]) -> Optional[Event]:
    tool = _optional_str(data.get("tool"))
    if tool is None:
        return None
    common = {
        "session_id": session_id,
        "attempt_id": attempt_id,
        "call_id": _optional_str(data.get("call_id")),
        "tool": tool,
        "elapsed_ms": _non_negative_int(data.get("elapsed_ms")),
        "preview": str(data.get("preview") or ""),
    }
    if data.get("status") == "ok":
        return ToolCompleted(**common, cached=data.get("cached") is True)
    return ToolFailed(**common)


def _terminal(event_cls: type, status: str) -> Builder:
    """Build a terminal-event builder that carries the run's result.

    Args:
        event_cls: RunCompleted, RunFailed or RunCancelled.
        status: The public status that event stands for.

    Returns:
        A builder for that terminal kernel event.
    """

    def build(session_id: str, attempt_id: str, data: Mapping[str, Any]) -> Event:
        run_dir = _optional_str(data.get("run_dir"))
        elapsed = data.get("elapsed_ms")
        result = RunResult(
            session_id=session_id,
            attempt_id=attempt_id,
            status=status,  # type: ignore[arg-type]
            text=str(data.get("summary") or ""),
            error=_optional_str(data.get("error")),
            provider=_optional_str(data.get("provider")),
            model=_optional_str(data.get("model")),
            run_dir=run_dir,
            usage=_read_usage(run_dir),
            elapsed_ms=_non_negative_int(elapsed) if elapsed is not None else None,
        )
        return event_cls(session_id=session_id, attempt_id=attempt_id, result=result)

    return build


#: Kernel event name -> builder. A name absent here is dropped; a builder
#: returning None drops a malformed payload rather than inventing fields.
EVENT_TABLE: Mapping[str, Builder] = MappingProxyType(
    {
        "attempt.started": _run_started,
        "text_delta": _text_delta,
        "stream_reset": _text_reset,
        "reasoning_delta": _reasoning_delta,
        "tool_call": _tool_started,
        "tool_result": _tool_finished,
        "attempt.completed": _terminal(RunCompleted, "completed"),
        "attempt.failed": _terminal(RunFailed, "failed"),
        "attempt.cancelled": _terminal(RunCancelled, "cancelled"),
    }
)


def translate(
    event_type: str, session_id: str, attempt_id: str, data: Mapping[str, Any]
) -> Optional[Event]:
    """Map one kernel event to a public event.

    Args:
        event_type: Kernel event name.
        session_id: Session the event belongs to.
        attempt_id: Attempt the stream follows.
        data: Kernel payload.

    Returns:
        The public event, or None when the name is not in the vocabulary or
        the payload lacks what the public event needs.
    """
    builder = EVENT_TABLE.get(event_type)
    if builder is None:
        return None
    return builder(session_id, attempt_id, data)
