"""Durable checkpoints for an assistant response that is still streaming."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, TYPE_CHECKING

from src.session.models import Attempt
from src.session.store import SessionStore

if TYPE_CHECKING:
    from src.session.runtime import SessionRuntime


class ResponseCheckpoint:
    """Persist a bounded-frequency snapshot of streamed assistant text.

    The first text chunk is written immediately. Later chunks are coalesced to
    avoid an fsync for every provider token, and :meth:`flush` captures the
    remaining buffer when the run leaves the streaming loop.
    """

    def __init__(
        self,
        store: SessionStore,
        attempt: Attempt,
        *,
        min_interval_seconds: float = 0.25,
        runtime: Optional["SessionRuntime"] = None,
    ) -> None:
        """Create a response checkpoint.

        Args:
            store: Session persistence store.
            attempt: Attempt whose response is being streamed.
            min_interval_seconds: Minimum time between snapshot writes.
        """
        self._store = store
        from src.session.runtime import SessionRuntime

        self._runtime = runtime or SessionRuntime(store.thread_log(attempt.session_id), attempt.session_id)
        self._session_id = attempt.session_id
        self._attempt_id = attempt.attempt_id
        self._min_interval_seconds = max(0.0, min_interval_seconds)
        self._text = ""
        self._dirty = False
        self._last_flush = 0.0
        self._lock = threading.Lock()

    def handle_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Apply an AgentLoop stream event to the durable snapshot.

        Args:
            event_type: Agent event name.
            data: Event payload.
        """
        if event_type != "item.delta" or data.get("kind") not in {"text.delta", "text.reset"}:
            return

        with self._lock:
            if data.get("kind") == "text.reset":
                self._text = ""
                self._dirty = True
                self._flush_locked()
                # The replacement stream's first chunk should be durable
                # immediately, just like the original stream's first chunk.
                self._last_flush = 0.0
                return

            delta = data.get("delta")
            if not isinstance(delta, str) or not delta:
                return
            self._text += delta
            self._dirty = True
            now = time.monotonic()
            if (
                self._last_flush == 0.0
                or now - self._last_flush >= self._min_interval_seconds
            ):
                self._flush_locked(now)

    @property
    def text(self) -> str:
        """Text streamed to the user so far, after any stream resets."""
        with self._lock:
            return self._text

    def flush(self) -> None:
        """Persist any text accumulated since the last snapshot."""
        with self._lock:
            self._flush_locked()

    def _flush_locked(self, now: float | None = None) -> None:
        if not self._dirty:
            return
        if self._runtime is not None:
            self._runtime.record_checkpoint(self._attempt_id, self._text)
        self._dirty = False
        self._last_flush = time.monotonic() if now is None else now
