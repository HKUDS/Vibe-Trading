"""Durable checkpoints for an assistant response that is still streaming."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, TYPE_CHECKING

from src.kernel import events as vocabulary
from src.session.models import Attempt
from src.session.store import SessionStore

if TYPE_CHECKING:
    from src.session.runtime import SessionRuntime


class ResponseCheckpoint:
    """Persist the first text chunk immediately and coalesce later writes until flush."""

    def __init__(
        self,
        store: SessionStore,
        attempt: Attempt,
        *,
        min_interval_seconds: float = 0.25,
        runtime: Optional["SessionRuntime"] = None,
    ) -> None:
        """Create a response checkpoint."""
        from src.session.runtime import SessionRuntime

        self._runtime = runtime or SessionRuntime(store.thread_log(attempt.session_id), attempt.session_id)
        self._attempt_id = attempt.attempt_id
        self._min_interval_seconds = max(0.0, min_interval_seconds)
        self._text = ""
        self._dirty = False
        self._last_flush = 0.0
        self._lock = threading.Lock()

    def handle_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Apply an AgentRuntime stream event to the durable snapshot."""
        if event_type != vocabulary.ITEM_DELTA or data.get("kind") not in {vocabulary.TEXT_DELTA, vocabulary.TEXT_RESET}:
            return

        with self._lock:
            if data.get("kind") == vocabulary.TEXT_RESET:
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
        self._runtime.record_checkpoint(self._attempt_id, self._text)
        self._dirty = False
        self._last_flush = time.monotonic() if now is None else now
