"""Bounded acquisition scheduling with foreground capacity and absolute deadlines."""

from concurrent.futures import Future
from contextvars import ContextVar, copy_context
from collections import deque
import threading
import time

background = ContextVar("gateway_background", default=False)
deadline = ContextVar("gateway_deadline", default=None)


class RequestQueue:
    """Two bounded queues; at most one worker may run background acquisition."""

    def __init__(self, workers, pending):
        self.condition = threading.Condition()
        self.queues = (deque(), deque())
        self.pending = pending
        self.active_background = 0
        self.local = threading.local()
        self.background_yields = 0
        self.closed = False
        self.threads = [
            threading.Thread(target=self._run, daemon=True, name=f"gateway-request-{i}") for i in range(workers)
        ]
        for thread in self.threads:
            thread.start()

    def submit(self, function, *args):
        with self.condition:
            for queue in self.queues:
                alive = [item for item in queue if not item[0].cancelled()]
                queue.clear()
                queue.extend(alive)
            if self.closed or sum(map(len, self.queues)) >= self.pending:
                raise RuntimeError("Request queue full or closed")
            future = Future()
            self.queues[int(background.get())].append((future, copy_context(), function, args))
            self.condition.notify_all()
            return future

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(
                    lambda: self.closed or self.queues[0] or (self.queues[1] and not self.active_background)
                )
                if self.closed:
                    return
                lane = 0 if self.queues[0] else 1
                future, context, function, args = self.queues[lane].popleft()
                self.active_background += lane
            try:
                self.local.background = bool(lane)
                if future.set_running_or_notify_cancel():
                    try:
                        future.set_result(context.run(function, *args))
                    except BaseException as exc:
                        future.set_exception(exc)
            finally:
                self.local.background = False
                # Drop completed results/tracebacks before waiting for more work.
                del future, context, function, args
                with self.condition:
                    self.active_background -= lane
                    self.condition.notify_all()

    def cooperate(self):
        """Run one waiting background request between source calls, on this thread.

        The outer request keeps its original deadline. Only a queue worker in
        the background lane can yield, and only one level of suspension is
        permitted. No extra coordinator or concurrent background source is
        created; cancelled futures and their captured contexts are discarded.
        """
        if not getattr(self.local, "background", False) or getattr(self.local, "yielding", False):
            return
        with self.condition:
            if self.closed or not self.queues[1]:
                return
            future, context, function, args = self.queues[1].popleft()
            self.background_yields += 1
        self.local.yielding = True
        try:
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(context.run(function, *args))
                except BaseException as exc:
                    future.set_exception(exc)
        finally:
            self.local.yielding = False
            del future, context, function, args

    def shutdown(self, wait=False, cancel_futures=True):
        cancelled = []
        with self.condition:
            self.closed = True
            for queue in self.queues:
                while queue:
                    cancelled.append(queue.popleft()[0])
            self.condition.notify_all()
        for future in cancelled:
            future.cancel()
        if wait:
            for thread in self.threads:
                thread.join()

    def status(self):
        with self.condition:
            return {
                "foreground_queued": len(self.queues[0]),
                "background_queued": len(self.queues[1]),
                "background_running": self.active_background,
                "background_yields": self.background_yields,
            }


class SourcePacer:
    """Space admissions per source without sleeping inside a network worker."""

    def __init__(self, spacing):
        self.spacing = spacing
        self.lock = threading.Lock()
        self.next = {}

    def acquire(self, source, until, cost=1):
        while time.monotonic() < until:
            with self.lock:
                now = time.monotonic()
                delay = self.next.get(source, 0) - now
                if delay <= 0:
                    self.next[source] = now + self.spacing * max(1, cost)
                    return True
            time.sleep(min(delay, max(0, until - time.monotonic())))
        return False

    def try_acquire(self, source, cost=1):
        """Admit without blocking a coordinator or holding a source thread idle."""
        with self.lock:
            now = time.monotonic()
            if self.next.get(source, 0) > now:
                return False
            self.next[source] = now + self.spacing * max(1, cost)
            return True
