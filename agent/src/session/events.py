"""Live session event bus, SSE encoding and durable cursor identifiers."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from src.kernel import events as vocabulary

logger = logging.getLogger(__name__)


@dataclass
class SSEEvent:
    """Server-sent event."""

    event_id: Optional[str] = field(default_factory=lambda: uuid.uuid4().hex[:16])
    event_type: str = "message"
    data: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)
    seq: Optional[int] = None

    def to_sse(self) -> str:
        """Format the event as an SSE text frame."""
        payload = json.dumps(self.data, ensure_ascii=False)
        lines = []
        if self.event_id:
            lines.append(f"id: {self.event_id}")
        lines.extend([
            f"event: {self.event_type}",
            f"data: {payload}",
            "",
            "",
        ])
        return "\n".join(lines)


class SubscriberQueue(asyncio.Queue):
    """Subscriber queue that remembers whether it ever dropped an event."""

    def __init__(self, maxsize: int = 0) -> None:
        super().__init__(maxsize=maxsize)
        self.overflowed = False


def _mark_overflow(queue: asyncio.Queue) -> None:
    if isinstance(queue, SubscriberQueue):
        queue.overflowed = True


def select_replay(
    buffer: List[SSEEvent],
    last_event_id: Optional[str] = None,
    *,
    replay_all: bool = False,
) -> List[SSEEvent]:
    """Choose the buffered events a reconnecting subscriber gets."""
    if not last_event_id:
        return list(buffer) if replay_all else []  # First connect: history loaded via REST by default.
    anchor = _buffer_anchor(buffer, last_event_id)
    return buffer[anchor:] if anchor is not None else list(buffer) if replay_all else []


def _buffer_anchor(buffer: List[SSEEvent], event_id: str) -> Optional[int]:
    return next((index for index, event in enumerate(buffer, 1) if event.event_id == event_id), None)


def select_buffered_live(
    buffer: List[SSEEvent], cursor: Optional[int], last_event_id: Optional[str],
    *, finished_live_ids: Optional[set[str]] = None,
) -> List[SSEEvent]:
    """Buffered live-only events a resuming client still needs."""
    anchor = _buffer_anchor(buffer, last_event_id) if last_event_id else None
    if anchor is None and cursor is not None:
        anchor = max(
            (index for index, event in enumerate(buffer, 1) if event.seq is not None and event.seq <= cursor),
            default=0,
        )
    finished = {
        event.data.get("live_id")
        for event in buffer
        if event.event_type == vocabulary.ITEM_COMPLETED and event.data.get("live_id")
    }
    finished.update(finished_live_ids or set())
    return [
        event for event in buffer[anchor:]
        if event.seq is None
        and not (
            event.event_type in (vocabulary.ITEM_STARTED, vocabulary.ITEM_DELTA)
            and event.data.get("live_id") in finished
        )
    ]

class EventBus:
    """Session-scoped live bus with subscribers and transient item events."""

    def __init__(self, max_buffer_size: int = 500, heartbeat_interval_s: float = 30.0) -> None:
        """Initialize the event bus."""
        self.max_buffer_size = max_buffer_size
        self.heartbeat_interval_s = heartbeat_interval_s
        self._buffers: Dict[str, List[SSEEvent]] = {}
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._listeners: List[Callable[[SSEEvent], None]] = []
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the asyncio event loop, usually during api_server startup."""
        self._loop = loop

    def publish(self, event: SSEEvent) -> None:
        """Publish an event to a session channel in a thread-safe way."""
        session_id = event.session_id
        with self._lock:
            buffer = self._buffers.setdefault(session_id, [])
            # Durable completions can be replayed from the thread.
            if event.seq is None and event.event_type in vocabulary.ITEM_EVENT_TYPES:
                buffer.append(event)
            if len(buffer) > self.max_buffer_size:
                self._buffers[session_id] = buffer[-self.max_buffer_size:]

            queues = list(self._subscribers.get(session_id, []))
            listeners = list(self._listeners)

        # A failing callback must never interrupt subscriber delivery.
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                logger.exception("EventBus listener failed for %s", event.event_type)

        for queue in queues:
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._safe_put, queue, event)
            else:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    _mark_overflow(queue)

    def add_listener(self, listener: Callable[[SSEEvent], None]) -> None:
        """Register a callback that runs synchronously on the publisher thread."""
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[SSEEvent], None]) -> None:
        """Unregister a callback, ignoring callbacks already absent."""
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    @staticmethod
    def _safe_put(queue: asyncio.Queue, event: SSEEvent) -> None:
        """Safely put an event onto a queue."""
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            _mark_overflow(queue)
            logger.warning("EventBus queue full, dropping %s event for session %s", event.event_type, event.session_id)

    def emit(
        self,
        session_id: str,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> SSEEvent:
        """Build and publish an event in one step."""
        event = SSEEvent(
            event_type=event_type,
            data=data or {},
            session_id=session_id,
        )
        self.publish(event)
        return event

    def replay(
        self,
        session_id: str,
        last_event_id: Optional[str] = None,
        *,
        replay_all: bool = False,
    ) -> List[SSEEvent]:
        """Replay buffered events after the last event ID, or the whole buffer for hydration."""
        with self._lock:
            return select_replay(
                self._buffers.get(session_id, []), last_event_id, replay_all=replay_all
            )

    def attach(self, session_id: str) -> Tuple["SubscriberQueue", List[SSEEvent]]:
        """Return a subscriber queue and its buffer snapshot taken under one lock."""
        queue = SubscriberQueue(maxsize=200)
        with self._lock:
            buffer = list(self._buffers.get(session_id, []))
            self._subscribers.setdefault(session_id, []).append(queue)
        return queue, buffer

    def detach(self, session_id: str, queue: asyncio.Queue) -> None:
        """Unregister a queue added by :meth:`attach`. Unknown queues are ignored."""
        with self._lock:
            subs = self._subscribers.get(session_id, [])
            if queue in subs:
                subs.remove(queue)

    async def listen(self, session_id: str, queue: asyncio.Queue) -> AsyncIterator[SSEEvent]:
        """Yield live events from an attached queue, with idle heartbeats."""
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=self.heartbeat_interval_s)
                except asyncio.TimeoutError:
                    yield SSEEvent(
                        event_id=None,
                        event_type="heartbeat",
                        data={"ts": time.time()},
                        session_id=session_id,
                    )
                    continue
                yield event
                if event.event_type == "session_cleared":
                    break
        finally:
            self.detach(session_id, queue)

    async def subscribe(
        self,
        session_id: str,
        last_event_id: Optional[str] = None,
        *,
        replay_all: bool = False,
    ) -> AsyncIterator[SSEEvent]:
        """Subscribe to a session event stream asynchronously."""
        queue, buffer = self.attach(session_id)
        try:
            for event in select_replay(buffer, last_event_id, replay_all=replay_all):
                yield event
            async for event in self.listen(session_id, queue):
                yield event
        finally:
            self.detach(session_id, queue)

    def clear(self, session_id: str) -> None:
        """Clear the buffered events and notify subscribers for a session."""
        with self._lock:
            self._buffers.pop(session_id, None)
            subs = self._subscribers.pop(session_id, [])

        sentinel = SSEEvent(
            event_id=None,
            event_type="session_cleared",
            data={},
            session_id=session_id,
        )
        for queue in subs:
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._safe_put, queue, sentinel)
            else:
                try:
                    queue.put_nowait(sentinel)
                except asyncio.QueueFull:
                    pass


# Rank of each event derived from one item, in emission order.
_STARTED, _COMPLETED, _RUN = 0, 1, 2
_DURABLE_SUFFIX = {_STARTED: "-started", _COMPLETED: "", _RUN: "-run"}
_DURABLE_ID_RE = re.compile(r"item-([1-9][0-9]*)(-started|-run)?")



def durable_event_id(seq: int, rank: int = _COMPLETED) -> str:
    """Return the SSE id of an event derived from one thread item."""
    return f"item-{seq}{_DURABLE_SUFFIX[rank]}"


def cursor_from_event_id(event_id: Optional[str]) -> Optional[int]:
    """Read the cursor a durable event id stands for."""
    if not event_id:
        return None
    match = _DURABLE_ID_RE.fullmatch(event_id)
    if match is None:
        return None
    seq = int(match.group(1))
    return seq - 1 if match.group(2) == "-started" else seq


def _event_key(event: SSEEvent) -> Tuple[int, int]:
    rank = _COMPLETED
    if event.event_type == vocabulary.ITEM_STARTED:
        rank = _STARTED
    elif event.event_type in vocabulary.RUN_EVENT_TYPES:
        rank = _RUN
    return (event.seq or 0, rank)
