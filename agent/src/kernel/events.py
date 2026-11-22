"""Round-two item and run event vocabulary shared by producers and consumers."""
from collections.abc import Callable
from typing import Any, TypeAlias

EventSink: TypeAlias = Callable[[str, dict[str, Any]], None]

ITEM_STARTED = "item.started"
ITEM_DELTA = "item.delta"
ITEM_COMPLETED = "item.completed"
ITEM_EVENT_TYPES = frozenset({ITEM_STARTED, ITEM_DELTA, ITEM_COMPLETED})

RUN_STARTED = "run.started"
RUN_COMPLETED = "run.completed"
RUN_FAILED = "run.failed"
RUN_CANCELLED = "run.cancelled"
RUN_WAITING_USER = "run.waiting_user"

#: ``turn_end`` status -> run event. A turn the process lost (``interrupted``)
#: is reported as a failure whose ``status`` says so.
RUN_TERMINAL_EVENTS: dict[str, str] = {
    "completed": RUN_COMPLETED,
    "failed": RUN_FAILED,
    "cancelled": RUN_CANCELLED,
    "interrupted": RUN_FAILED,
    "waiting_user": RUN_WAITING_USER,
}
RUN_EVENT_TYPES = frozenset({RUN_STARTED, *RUN_TERMINAL_EVENTS.values()})

#: Kind of a live item that the thread never recorded (a response the loop
#: dropped, a call cut off by the end of its turn).
DISCARDED_KIND = "item.discarded"

# Lifecycle kinds carried inside item events.
TEXT_DELTA = "text.delta"
TEXT_RESET = "text.reset"
REASONING_DELTA = "reasoning.delta"
TOOL_STARTED = "tool.started"
TOOL_PROGRESS = "tool.progress"
TOOL_COMPLETED = "tool.completed"
TOOL_FAILED = "tool.failed"
RUN_USAGE = "run.usage"
RUN_USAGE_UNAVAILABLE = "run.usage_unavailable"
RUN_WAITING = "run.waiting"
RUN_STALL_WARNING = "run.stall_warning"
RUN_STALLED = "run.stalled"
CONTEXT_COMPACTED = "context.compacted"
