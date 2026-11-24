"""Supervise a provider stream whose next chunk may never arrive."""

from __future__ import annotations

import contextvars
import inspect
import queue
import threading
import time
from typing import Any, Callable, Iterator, Optional, TypeVar

_EXHAUSTED = object()

#: How long a close is given to take effect before it is left to the adapter.
_CLOSE_JOIN_SECONDS = 2.0


class StreamInterrupted(Exception):
    """A stream was stopped before it delivered a usable answer.

    Args:
        reason: Reason for interruption, such as cancellation or an idle or total timeout.
        emitted: Whether an item already reached the consumer.
        pending: Undelivered chunk, when present, whose billed usage the caller may recover.
    """

    def __init__(self, reason: str, *, emitted: bool = False, pending: Any = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.emitted = emitted
        # Retain billed usage from the pending chunk on interruption.
        self.pending = pending


class _Puller:
    """Move items off a blocking iterator one at a time onto a queue."""

    def __init__(self, iterator: Iterator[Any], out: "queue.Queue[Any]") -> None:
        self._iterator = iterator
        self._out = out
        self._stop = threading.Event()
        self._close_lock = threading.Lock()
        self._closed = False
        context = contextvars.copy_context()
        self._thread = threading.Thread(
            target=context.run, args=(self._run,), daemon=True, name="stream-pull"
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    item = next(self._iterator)
                except StopIteration:
                    self._put(_EXHAUSTED)
                    return
                except BaseException as exc:  # noqa: BLE001 - forwarded to caller
                    self._put(exc)
                    return
                self._put(item)
        finally:
            # Release a busy generator on the pull thread after next() returns.
            self._close_once()

    def _close_once(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            close = getattr(self._iterator, "close", None)
            if callable(close):
                try:
                    close()
                except BaseException:
                    return
            self._closed = True

    def _put(self, item: Any) -> None:
        # Poll for cancellation without dropping data, errors or EOF.
        while not self._stop.is_set():
            try:
                self._out.put(item, timeout=0.05)
                return
            except queue.Full:
                continue

    def stop(self) -> None:
        self._stop.set()

    def close_iterator(self) -> None:
        """Close the underlying iterator, bounded so a busy generator cannot hang us."""
        # Only the owner may finalize a busy generator.
        if inspect.isgenerator(self._iterator) or self._closed:
            return
        if not callable(getattr(self._iterator, "close", None)):
            return
        # Bound custom close() calls that can unblock next().
        done = threading.Event()

        def _attempt() -> None:
            try:
                self._close_once()
            except BaseException:  # noqa: BLE001 - best effort release
                pass
            finally:
                done.set()

        worker = threading.Thread(target=_attempt, daemon=True, name="stream-close")
        worker.start()
        done.wait(_CLOSE_JOIN_SECONDS)


def supervised_pulls(
    iterator: Iterator[Any],
    *,
    idle_timeout_s: Optional[float] = None,
    total_timeout_s: Optional[float] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    poll_interval_s: float = 0.05,
) -> Iterator[Any]:
    """Yield items while the stream can still make progress.

    Args:
        iterator: Source iterator, which may block in next.
        idle_timeout_s: Maximum seconds waiting for the next item, excluding consumer time. None or
            zero disables the idle deadline.
        total_timeout_s: Maximum seconds for the supervised stream. None or zero disables the total
            deadline.
        should_cancel: Optional cancellation predicate checked before pulling and while waiting.
        poll_interval_s: Seconds between cancellation polls while waiting for an item.

    Yields:
        Source items until exhaustion, cancellation, or timeout.

    Raises:
        StreamInterrupted: If a deadline expires or cancellation is requested.
        BaseException: If a supervised pull raises an exception from the source iterator.
    """
    idle_timeout_s = idle_timeout_s or None
    total_timeout_s = total_timeout_s or None
    if idle_timeout_s is None and total_timeout_s is None and should_cancel is None:
        yield from iterator
        return

    out: "queue.Queue[Any]" = queue.Queue(maxsize=1)
    if should_cancel is not None and should_cancel():
        raise StreamInterrupted("cancelled")
    puller = _Puller(iterator, out)
    started = time.monotonic()
    last_chunk = started
    emitted = False

    def interrupt(reason: str) -> StreamInterrupted:
        # Keep already billed usage when discarding interrupted output.
        try:
            pending = out.get_nowait()
        except queue.Empty:
            pending = None
        if pending is _EXHAUSTED or isinstance(pending, BaseException):
            pending = None
        return StreamInterrupted(reason, emitted=emitted, pending=pending)

    try:
        while True:
            now = time.monotonic()
            remaining: Optional[float] = None
            if idle_timeout_s is not None:
                remaining = max(0.0, idle_timeout_s - (now - last_chunk))
            if total_timeout_s is not None:
                budget = max(0.0, total_timeout_s - (now - started))
                remaining = budget if remaining is None else min(remaining, budget)
            if remaining is not None and remaining <= 0:
                total_expired = total_timeout_s is not None and now - started >= total_timeout_s
                raise interrupt("total timeout" if total_expired else "idle timeout")
            wait = poll_interval_s if remaining is None else min(poll_interval_s, remaining)
            try:
                item = out.get(timeout=wait)
            except queue.Empty:
                # Check cancellation after polling so already billed chunks can be retained.
                if should_cancel is not None and should_cancel():
                    raise interrupt("cancelled")
                continue
            if item is _EXHAUSTED:
                return
            if isinstance(item, BaseException):
                raise item
            emitted = True
            yield item
            # Time spent in the consumer is not provider silence.
            last_chunk = time.monotonic()
    finally:
        puller.stop()
        puller.close_iterator()


Chunk = TypeVar("Chunk")


def threaded_stream(
    run: Callable[[Callable[[Chunk], None], threading.Event], None],
    *,
    heartbeat: Callable[[], Chunk] | None = None,
    interval: float | None = None,
) -> Iterator[Chunk]:
    """Yield worker output and signal cancellation when the consumer closes.

    Args:
        run: Worker function receiving an item emitter and an event set when consumption ends.
        heartbeat: Optional factory for a heartbeat item when the output queue is idle.
        interval: Seconds to wait for worker output between heartbeats. None waits without a
            deadline.

    Yields:
        Worker output and any configured heartbeat items.

    Raises:
        Exception: If the worker or heartbeat factory raises.
    """
    chunks: queue.Queue[Any] = queue.Queue()
    sentinel = object()
    cancelled = threading.Event()

    def produce() -> None:
        try:
            run(chunks.put, cancelled)
        except Exception as exc:
            chunks.put(exc)
        finally:
            chunks.put(sentinel)

    threading.Thread(target=produce, daemon=True).start()
    try:
        while True:
            try:
                chunk = chunks.get(timeout=interval)
            except queue.Empty:
                if heartbeat is not None:
                    yield heartbeat()
                continue
            if chunk is sentinel:
                return
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk
    finally:
        cancelled.set()
