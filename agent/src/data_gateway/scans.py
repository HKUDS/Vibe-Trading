"""Bounded background acquisition jobs; failures are retried with backpressure."""

from collections import deque
import threading
import time
import uuid

from .scheduling import background


class ScanQueue:
    """Acquire a universe in HTTP-sized batches, yielding capacity to subscribers.

    Jobs retain coverage metadata, not OHLC frames. Acquired frames use the
    existing quota-bounded cache. This is acquisition, not an indicator screener
    or a durable whole-market dataset; historical datasets have a separate API.
    """

    def __init__(self, gateway):
        self.gateway = gateway
        self.condition = threading.Condition(threading.RLock())
        self.jobs = {}
        self.closed = False
        self.thread = threading.Thread(target=self._run, daemon=True, name="gateway-scan")
        self.thread.start()

    def _prune(self):
        now = time.monotonic()
        for key, job in list(self.jobs.items()):
            if (
                job["state"] in {"complete", "partial", "cancelled"}
                and now - job["updated"] > self.gateway.config.memory_idle
            ):
                del self.jobs[key]

    def create(self, codes, **params):
        """Enqueue a bounded public universe; return immediately with its job id."""
        from .api import BarsRequest

        codes = list(dict.fromkeys(codes))
        if not codes or len(codes) > self.gateway.config.scan_symbols:
            raise ValueError("Scan symbol capacity exceeded")
        for start in range(0, len(codes), 8):
            BarsRequest(codes=codes[start : start + 8], **params)
        with self.condition:
            self._prune()
            if (
                self.closed
                or len(self.jobs) >= 4
                or sum(j["total"] for j in self.jobs.values()) + len(codes) > self.gateway.config.scan_symbols
            ):
                raise ValueError("Scan queue full; retry after existing jobs finish or expire")
            identity = uuid.uuid4().hex
            self.jobs[identity] = {
                "id": identity,
                "state": "queued",
                "total": len(codes),
                "completed": 0,
                "attempts": 0,
                "failed": [],
                "waiting": deque((code, 0, 0.0) for code in codes),
                "params": params,
                "updated": time.monotonic(),
                "retries": 0,
                "last_error": None,
                "batches": 0,
                "acquisition_seconds": 0.0,
                "backoff_seconds": 0.0,
            }
            self.condition.notify_all()
            return self.status(identity)

    def status(self, identity=None):
        """Return bounded progress; failed symbols are available separately."""
        with self.condition:
            self._prune()
            if identity is None:
                return [self._summary(job) for job in self.jobs.values()]
            if identity not in self.jobs:
                raise ValueError("Unknown or expired scan")
            return self._summary(self.jobs[identity])

    @staticmethod
    def _summary(job):
        return {
            **{key: job[key] for key in ("id", "state", "total", "completed", "attempts", "retries", "last_error")},
            "failed": len(job["failed"]),
            "remaining": job["total"] - job["completed"] - len(job["failed"]),
            "complete": job["state"] == "complete",
            "retention": "idle metadata expires; frames use shared cache",
            "batches": job["batches"],
            "acquisition_seconds": round(job["acquisition_seconds"], 3),
            "backoff_seconds": round(job["backoff_seconds"], 3),
        }

    def failures(self, identity, offset=0, limit=100):
        with self.condition:
            self.status(identity)
            return self.jobs[identity]["failed"][max(0, offset) : max(0, offset) + min(100, max(1, limit))]

    def cancel(self, identity):
        with self.condition:
            self.status(identity)
            job = self.jobs[identity]
            job.update(state="cancelled", updated=time.monotonic())
            job["waiting"].clear()
            self.condition.notify_all()
            return self._summary(job)

    def _run(self):
        background.set(True)
        while True:
            with self.condition:
                self._prune()
                if self.closed:
                    return
                ready = None
                now = time.monotonic()
                for job in self.jobs.values():
                    if job["state"] in {"queued", "running"} and job["waiting"]:
                        # Rotate delayed retries so a failed symbol cannot block
                        # the rest of the universe. The queue is always bounded.
                        for _ in range(len(job["waiting"])):
                            item = job["waiting"].popleft()
                            if item[2] <= now:
                                ready = job, item
                                break
                            job["waiting"].append(item)
                    if ready:
                        break
                if ready is None:
                    self.condition.wait(timeout=1)
                    continue
                job, first = ready
                items = [first]
                for _ in range(len(job["waiting"])):
                    if len(items) >= min(8, self.gateway.config.http_batch_symbols):
                        break
                    item = job["waiting"].popleft()
                    if item[2] <= now:
                        items.append(item)
                    else:
                        job["waiting"].append(item)
                job["state"] = "running"
                job["attempts"] += len(items)
            started = time.monotonic()
            value = None
            successes = set()
            try:
                value = self.gateway.bars(codes=[item[0] for item in items], **job["params"])
                if value.get("ok"):
                    successes = set(value.get("data", {}).get("_provenance", {}))
                retry_after = max(
                    self.gateway.config.scan_spacing,
                    float(value.get("retry_after_seconds", self.gateway.config.cooldown)),
                )
                error = value.get("error", "Symbol missing from source response")
            except Exception as exc:
                retry_after, error = self.gateway.config.cooldown, type(exc).__name__
            with self.condition:
                if job["state"] != "cancelled":
                    for code, attempt, _ in items:
                        if code in successes:
                            job["completed"] += 1
                        elif attempt + 1 < self.gateway.config.scan_attempts:
                            job["waiting"].append(
                                (code, attempt + 1, time.monotonic() + min(300, retry_after * 2**attempt))
                            )
                            job["retries"] += 1
                            job["last_error"] = str(error)[:160]
                        else:
                            job["failed"].append(code)
                    if not job["waiting"]:
                        job["state"] = "partial" if job["failed"] else "complete"
                    job["updated"] = time.monotonic()
                job["batches"] += 1
                job["acquisition_seconds"] += time.monotonic() - started
                # Each missing symbol already has its own retry deadline. A partial
                # batch must not freeze unrelated ready symbols for that cooldown.
                # A completely unavailable batch still backs off the whole scanner;
                # the shared source pacer and bounded background lane also remain.
                delay = self.gateway.config.scan_spacing if successes else min(300, retry_after)
                del value, successes, items
                waiting = time.monotonic()
                self.condition.wait(timeout=delay)
                job["backoff_seconds"] += time.monotonic() - waiting

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.thread.join(timeout=self.gateway.config.request_timeout + 1)
        with self.condition:
            self.jobs.clear()
