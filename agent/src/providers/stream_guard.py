"""Supervise a provider stream whose next chunk may never arrive.

A synchronous provider iterator blocks inside ``next()`` while the wire is
silent, so a caller that polls a timeout or a cancel flag *after* each chunk
never gets to poll at all. This races the pull against the idle deadline, the
total deadline and a cancel predicate, and requests iterator cleanup when the
wait is interrupted.

Closing is best effort for a synchronous iterator already inside next(). The
caller stops waiting promptly; the pull thread closes a busy iterator when it
returns. Adapters remain responsible for bounding their underlying socket I/O.
"""

from __future__ import annotations

import contextvars
import inspect
import queue
import threading
import time
from typing import Any, Callable, Iterator, Optional

#: Sentinel for "the iterator is exhausted".
_EXHAUSTED = object()

#: How long a close is given to take effect before it is left to the adapter.
_CLOSE_JOIN_SECONDS = 2.0


class StreamInterrupted(Exception):
    """A stream was stopped before it delivered a usable answer.

    Carries the reason so the caller can tell a user stop from a stall, and
    whether any partial output was already handed out, because that decides
    whether a fallback request would replay a turn the user has already seen.
    """

    def __init__(self, reason: str, *, emitted: bool = False, pending: Any = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.emitted = emitted
        #: A chunk the provider had already produced when the stream stopped.
        #: Its usage was billed, so the caller keeps it even though its text
        #: and tool calls are dropped.
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
            # A busy generator rejects cross-thread close(). Once next() returns,
            # this owning thread can release it, even after the caller has left.
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
        # Backpressure must never discard text, usage, errors or EOF. Polling
        # permits cancellation while a slow consumer leaves the slot occupied.
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
        # Never close a generator concurrently with its owner. Besides raising
        # "generator already executing", concurrent finalization is unsafe in
        # some Python runtimes. The owner closes it in _run's finally block.
        if inspect.isgenerator(self._iterator) or self._closed:
            return
        if not callable(getattr(self._iterator, "close", None)):
            return
        # Custom adapters may expose a close that unblocks next(). Bound that
        # operation too; the caller must not hang inside adapter cleanup.
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

    Raises :class:`StreamInterrupted` when the idle deadline passes with no
    chunk, the total deadline expires, or ``should_cancel`` turns true. The
    iterator receives a bounded cleanup attempt; a busy generator is closed
    by its owning thread when next() returns. Queued late text is not emitted.
    """
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
        # Take whatever the provider already produced: it was billed, so its
        # usage belongs on the response even though its text is dropped.
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
                # Nothing arrived in this window, so the only thing that can
                # still make progress is stopping. A chunk that has already
                # arrived is always preferred, because it was already billed
                # and the consumer keeps its usage even while dropping text.
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
