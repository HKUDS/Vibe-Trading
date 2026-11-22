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
    """Server-sent event.

    Attributes:
        event_id: Globally unique event ID used for last_event_id recovery.
        event_type: Event type stored in the SSE ``event`` field.
        data: Event payload.
        session_id: Owning session ID.
        timestamp: Event timestamp.
        seq: Thread item seq for an event derived from a recorded item (it can
            be rebuilt from disk); None for a live-only event.
    """

    event_id: Optional[str] = field(default_factory=lambda: uuid.uuid4().hex[:16])
    event_type: str = "message"
    data: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)
    seq: Optional[int] = None

    def to_sse(self) -> str:
        """Format the event as an SSE text frame.

        Returns:
            Text that conforms to the SSE specification.
        """
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
    """Subscriber queue that remembers whether it ever dropped an event.

    Attributes:
        overflowed: Set when an event was dropped because the queue was full.
            A durable-stream reader clears it after re-reading the log.
    """

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
    """Choose the buffered events a reconnecting subscriber gets.

    Args:
        buffer: The session's buffered events, oldest first.
        last_event_id: Last event ID the client received.
        replay_all: Return the whole buffer when ``last_event_id`` is absent
            or not buffered (active-run hydration).

    Returns:
        Events after ``last_event_id``; the whole buffer or nothing when it is
        absent, per ``replay_all``.
    """
    if not last_event_id:
        return list(buffer) if replay_all else []  # First connect: history loaded via REST by default.
    found = False
    result: List[SSEEvent] = []
    for event in buffer:
        if found:
            result.append(event)
        elif event.event_id == last_event_id:
            found = True
    if not found and replay_all:
        return list(buffer)
    return result


def select_buffered_live(
    buffer: List[SSEEvent], cursor: Optional[int], last_event_id: Optional[str],
    *, finished_live_ids: Optional[set[str]] = None,
) -> List[SSEEvent]:
    """Buffered live-only events a resuming client still needs."""
    anchor = 0
    found = False
    if last_event_id:
        for index, event in enumerate(buffer):
            if event.event_id == last_event_id:
                anchor, found = index + 1, True
                break
    if not found and cursor is not None:
        for index, event in enumerate(buffer):
            if event.seq is not None and event.seq <= cursor:
                anchor = index + 1
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
    """Session-scoped live bus with subscribers and transient item events.

    V5: Inject the asyncio event loop with ``set_loop()``, and use
    ``call_soon_threadsafe`` in ``publish()`` to preserve thread safety.

    Attributes:
        max_buffer_size: Maximum number of in-progress events retained per
            session. Durable item completions are read from ``thread.jsonl``.
    """

    def __init__(self, max_buffer_size: int = 500, heartbeat_interval_s: float = 30.0) -> None:
        """Initialize the event bus.

        Args:
            max_buffer_size: Maximum number of buffered events per session.
            heartbeat_interval_s: Idle seconds before a subscriber is sent a
                ``heartbeat`` frame. Also bounds how long a subscriber waiting
                on an idle queue takes to notice a cross-thread publish when no
                loop was injected via :meth:`set_loop`.
        """
        self.max_buffer_size = max_buffer_size
        self.heartbeat_interval_s = heartbeat_interval_s
        self._buffers: Dict[str, List[SSEEvent]] = {}
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._listeners: List[Callable[[SSEEvent], None]] = []
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the asyncio event loop, usually during api_server startup.

        Args:
            loop: asyncio event loop.
        """
        self._loop = loop

    def publish(self, event: SSEEvent) -> None:
        """Publish an event to a session channel in a thread-safe way.

        Args:
            event: Event to publish.
        """
        session_id = event.session_id
        with self._lock:
            if session_id not in self._buffers:
                self._buffers[session_id] = []
            buffer = self._buffers[session_id]
            # Completed item events have a durable cursor and never need the
            # ring buffer. Keep only live item events so reconnects can retain
            # an in-progress delta while the thread remains the source of
            # truth for everything that completed.
            if event.seq is None and event.event_type in vocabulary.ITEM_EVENT_TYPES:
                buffer.append(event)
            if len(buffer) > self.max_buffer_size:
                self._buffers[session_id] = buffer[-self.max_buffer_size:]

            queues = list(self._subscribers.get(session_id, []))
            listeners = list(self._listeners)

        # Listeners run before the queues so a slow subscriber cannot delay
        # them, and each is isolated: this is the SSE hot path, and a listener
        # that raises must not cost the UI its event stream. A listener is
        # expected to record or schedule, never to do I/O inline.
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                logger.exception("EventBus listener failed for %s", event.event_type)

        # Safely enqueue onto the queue from inside the asyncio loop.
        for queue in queues:
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._safe_put, queue, event)
            else:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    _mark_overflow(queue)

    def add_listener(self, listener: Callable[[SSEEvent], None]) -> None:
        """Register a callback invoked for every published event.

        Unlike :meth:`subscribe`, which is per session and per SSE connection,
        a listener sees every session — which is what a component that reacts
        to runs it did not open needs.

        Args:
            listener: Synchronous callback. It runs on the publishing thread,
                so it must be cheap and must not raise; schedule any real work
                elsewhere.
        """
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[SSEEvent], None]) -> None:
        """Unregister a callback added by :meth:`add_listener`.

        Args:
            listener: The previously registered callback. Unknown callbacks
                are ignored so teardown never has to check first.
        """
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    @staticmethod
    def _safe_put(queue: asyncio.Queue, event: SSEEvent) -> None:
        """Safely put an event onto a queue.

        Args:
            queue: asyncio queue.
            event: SSE event.
        """
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
        """Build and publish an event in one step.

        Args:
            session_id: Session ID.
            event_type: Event type.
            data: Event payload.

        Returns:
            The published SSEEvent.
        """
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
        """Replay buffered session events for reconnect recovery.

        Args:
            session_id: Session ID.
            last_event_id: Last event ID received by the client.
            replay_all: Return the buffered stream from the beginning when
                ``last_event_id`` is absent. Used only for active run recovery;
                completed history is loaded through REST.

        Returns:
            List of events that should be replayed.
        """
        with self._lock:
            return self._replay_locked(session_id, last_event_id, replay_all=replay_all)

    def _replay_locked(
        self,
        session_id: str,
        last_event_id: Optional[str] = None,
        *,
        replay_all: bool = False,
    ) -> List[SSEEvent]:
        """Compute the replay list. Caller must already hold ``self._lock``."""
        return select_replay(
            self._buffers.get(session_id, []), last_event_id, replay_all=replay_all
        )

    def attach(self, session_id: str) -> Tuple["SubscriberQueue", List[SSEEvent]]:
        """Register a subscriber queue and snapshot the buffer atomically.

        The snapshot and the registration share one lock acquisition, so every
        event is either in the snapshot or delivered to the queue, never both
        and never neither. The caller must hand the queue to :meth:`listen`
        (which unregisters it) or call :meth:`detach`.

        Args:
            session_id: Session ID.

        Returns:
            ``(queue, buffered events)``.
        """
        queue = SubscriberQueue(maxsize=200)
        with self._lock:
            buffer = list(self._buffers.get(session_id, []))
            self._subscribers.setdefault(session_id, []).append(queue)
        return queue, buffer

    def detach(self, session_id: str, queue: asyncio.Queue) -> None:
        """Unregister a queue added by :meth:`attach`. Unknown queues are ignored.

        Args:
            session_id: Session ID.
            queue: The subscriber queue.
        """
        with self._lock:
            subs = self._subscribers.get(session_id, [])
            if queue in subs:
                subs.remove(queue)

    async def listen(self, session_id: str, queue: asyncio.Queue) -> AsyncIterator[SSEEvent]:
        """Yield live events from an attached queue, with idle heartbeats.

        Ends after a ``session_cleared`` sentinel and always detaches the queue.

        Args:
            session_id: Session ID.
            queue: Queue returned by :meth:`attach`.

        Yields:
            SSEEvent objects.
        """
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
                if event.event_type == "session_cleared":
                    yield event
                    break
                yield event
        finally:
            self.detach(session_id, queue)

    async def subscribe(
        self,
        session_id: str,
        last_event_id: Optional[str] = None,
        *,
        replay_all: bool = False,
    ) -> AsyncIterator[SSEEvent]:
        """Subscribe to a session event stream asynchronously.

        Args:
            session_id: Session ID.
            last_event_id: Last event ID received by the client for reconnect recovery.
            replay_all: Replay all buffered events when no last event ID is
                available. This is opt-in for active run hydration.

        Yields:
            SSEEvent objects.
        """
        queue, buffer = self.attach(session_id)
        try:
            for event in select_replay(buffer, last_event_id, replay_all=replay_all):
                yield event
            async for event in self.listen(session_id, queue):
                yield event
        finally:
            self.detach(session_id, queue)

    def clear(self, session_id: str) -> None:
        """Clear the buffered events and notify subscribers for a session.

        Subscriber queues receive a ``session_cleared`` sentinel event so
        they can break out of their ``while True`` loop instead of waiting
        indefinitely on a cleared session. The subscriber list is then
        dropped so future ``publish`` calls do not enqueue to dead queues.

        Args:
            session_id: Session ID.
        """
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
    """Return the SSE id of an event derived from one thread item.

    The id depends only on the item, so the live event and the copy rebuilt
    from disk carry the same id and a client deduplicates them by id.

    Args:
        seq: Item seq.
        rank: 0 for ``item.started``, 1 for ``item.completed``, 2 for the run
            event of a turn boundary.

    Returns:
        ``item-<seq>``, ``item-<seq>-started`` or ``item-<seq>-run``.
    """
    return f"item-{seq}{_DURABLE_SUFFIX[rank]}"


def cursor_from_event_id(event_id: Optional[str]) -> Optional[int]:
    """Read the cursor a durable event id stands for.

    Args:
        event_id: A ``Last-Event-ID`` value.

    Returns:
        The seq through which the client has every completed item, or None
        when the id is not a durable one (a live event's random id).
    """
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
