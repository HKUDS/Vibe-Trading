"""Supervise a provider stream whose next chunk may never arrive.

A synchronous provider iterator blocks inside ``next()`` while the wire is
silent, so a caller that polls a timeout or a cancel flag *after* each chunk
never gets to poll at all. This races the pull against the idle deadline, the
total deadline and a cancel predicate, and when that race is lost it closes the
iterator before reporting the interruption.

Closing is the point. Abandoning the pull and returning would leave the
transport open and make the caller believe the stream stopped when only its
consumer did.
"""

from __future__ import annotations

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
        self._thread = threading.Thread(target=self._run, daemon=True, name="stream-pull")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = next(self._iterator)
            except StopIteration:
                self._put(_EXHAUSTED)
                return
            except BaseException as exc:  # noqa: BLE001 - forwarded to the caller
                self._put(exc)
                return
            self._put(item)

    def _put(self, item: Any) -> None:
        try:
            self._out.put(item, timeout=1.0)
        except queue.Full:
            return

    def stop(self) -> None:
        self._stop.set()

    def close_iterator(self) -> None:
        """Close the underlying iterator, bounded so a busy generator cannot hang us."""
        close = getattr(self._iterator, "close", None)
        if not callable(close):
            return
        # A generator that is mid-execution cannot be closed from here; that is
        # a limitation of the synchronous iterator protocol, not a decision to
        # leave the transport open, so it is attempted and bounded either way.
        done = threading.Event()

        def _attempt() -> None:
            try:
                close()
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
    iterator is closed before the exception leaves, and any item that was
    already queued is discarded rather than delivered late.
    """
    if idle_timeout_s is None and total_timeout_s is None and should_cancel is None:
        yield from iterator
        return

    out: "queue.Queue[Any]" = queue.Queue(maxsize=1)
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
                raise interrupt("idle timeout" if idle_timeout_s is not None else "total timeout")
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
            last_chunk = time.monotonic()
            emitted = True
            yield item
    finally:
        puller.stop()
        puller.close_iterator()
