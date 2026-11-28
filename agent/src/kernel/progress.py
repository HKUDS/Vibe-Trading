"""Route tool heartbeats and thread-local progress to the owning run."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProgressEvent:
    """Report tool progress with optional unit counts and wall-clock timing."""

    tool: str = ""
    stage: str = ""
    current: Optional[int] = None
    total: Optional[int] = None
    message: str = ""
    elapsed_s: float = 0.0
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize progress for transport in an SSE payload.

        Returns:
            JSON-serializable fields with elapsed seconds rounded to two decimal places.
        """
        return {
            "tool": self.tool,
            "stage": self.stage,
            "current": self.current,
            "total": self.total,
            "message": self.message,
            "elapsed_s": round(self.elapsed_s, 2),
            "ts": self.ts,
        }


# Isolate progress emitters so concurrent tools report to the correct run.
_local = threading.local()


def _set_emitter(emit: Optional[Callable[[ProgressEvent], None]]) -> None:
    """Install the active progress emitter for the current thread."""
    if emit is None:
        if hasattr(_local, "emit"):
            del _local.emit
        return
    _local.emit = emit


def _get_emitter() -> Optional[Callable[[ProgressEvent], None]]:
    """Return the active emitter on the current thread, if any."""
    return getattr(_local, "emit", None)


def emit_progress(
    stage: str = "",
    *,
    current: Optional[int] = None,
    total: Optional[int] = None,
    message: str = "",
) -> None:
    """Publish a structured progress event from a tool.

    Silently no-ops when called outside an active tool context.

    Args:
        stage: Short stage label.
        current: Current unit count, if known.
        total: Total unit count, if known.
        message: Free-form human-readable detail.
    """
    emit = _get_emitter()
    if emit is None:
        return
    try:
        event = ProgressEvent(
            stage=stage,
            current=current,
            total=total,
            message=message,
        )
        emit(event)
    except Exception:
        # Progress emission must never break a tool.
        pass


class HeartbeatTimer:
    """Emit keepalive ticks during a tool invocation and bound the wait on context exit.

    Args:
        tool_name: Tool name surfaced in each tick payload.
        interval: Seconds between ticks. Values below 0.5 are clamped.
        emit: Callback invoked with each tick payload.
    """

    def __init__(
        self,
        tool_name: str,
        interval: float,
        emit: Callable[[Dict[str, Any]], None],
    ) -> None:
        """Configure heartbeats with a minimum interval of 0.5 seconds."""
        self._tool_name = tool_name
        requested_interval = float(interval)
        self._interval = max(0.5, requested_interval)
        if requested_interval < 0.5:
            logger.warning(
                "HeartbeatTimer interval %s clamped to 0.5s", interval
            )
        self._emit = emit
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._t0 = 0.0

    def __enter__(self) -> "HeartbeatTimer":
        self._t0 = time.perf_counter()
        self._thread = threading.Thread(
            target=self._run,
            name=f"heartbeat-{self._tool_name}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        """Tick loop: wait + emit until the stop event fires."""
        while not self._stop_event.wait(self._interval):
            elapsed = time.perf_counter() - self._t0
            try:
                self._emit({"tool": self._tool_name, "elapsed_s": round(elapsed, 2)})
            except Exception:
                # A failing callback must not crash the heartbeat thread.
                pass
