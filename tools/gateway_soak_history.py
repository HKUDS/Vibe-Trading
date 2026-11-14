"""Optional combined live/history workload for gateway_soak; no synthetic prices."""

import asyncio
from collections import defaultdict, deque
import socket
import sys
import threading
import time


class Timings:
    """Bound measurement overhead independently of experiment duration."""

    def __init__(self):
        self.lock = threading.Lock()
        self.values = defaultdict(lambda: deque(maxlen=4096))
        self.counts = defaultdict(int)

    def add(self, kind, seconds):
        with self.lock:
            self.values[kind].append(round(seconds * 1000, 3))
            self.counts[kind] += 1

    def summary(self):
        with self.lock:
            result = {}
            for kind, values in self.values.items():
                ordered = sorted(values)
                result[kind] = {
                    "count": self.counts[kind],
                    "retained": len(ordered),
                    "p50_ms": ordered[int((len(ordered) - 1) * 0.50)],
                    "p95_ms": ordered[int((len(ordered) - 1) * 0.95)],
                    "max_ms": ordered[-1],
                }
            return result


def instrument_history(fault, counts, timings):
    """Inject failures at the actual production fetch boundary in this child."""
    from src.data_gateway.history_store import get_history_store

    store = get_history_store()
    original = store.fetcher

    def fetch(*args):
        counts["history_attempts"] += 1
        if fault["mode"] == "all_offline":
            counts["history_refused"] += 1
            raise ConnectionError("soak injected history network unavailable")
        epoch = fault["epoch"]
        started = time.monotonic()
        try:
            result = original(*args)
            if fault["epoch"] != epoch:
                raise ConnectionError("soak history transport interrupted")
        except Exception:
            timings.add("history_chunk_failed", time.monotonic() - started)
            counts["history_failed"] += 1
            raise
        timings.add("history_chunk_success", time.monotonic() - started)
        counts["history_success"] += 1
        counts["history_rows"] += len(result[0])
        return result

    store.fetcher = fetch
    return store


def abort_history(counts):
    """Interrupt only this isolated child's current BaoStock transport."""
    module = sys.modules.get("baostock.common.context")
    connection = getattr(module, "default_socket", None)
    if connection is not None:
        try:
            connection.shutdown(socket.SHUT_RDWR)
            counts["history_socket_aborted"] += 1
        except OSError:
            pass
        connection.close()


class HistoryDriver:
    """Keep real multi-year downloads overlapping every active test cycle."""

    def __init__(self, client, url, checks, started):
        self.client, self.url, self.checks, self.started = client, url, checks, started
        self.stop = asyncio.Event()
        self.current = None
        self.completed = []
        self.error = None
        self.round = 0

    def record(self, kind, **values):
        self.checks.append({"kind": kind, "elapsed_s": round(time.monotonic() - self.started, 2), **values})

    async def request(self, method, path, **kwargs):
        response = await self.client.request(method, self.url + path, **kwargs)
        response.raise_for_status()
        return response.json()

    async def run(self):
        try:
            while not self.stop.is_set():
                if self.current is None:
                    interval = ["5m", "15m", "30m", "1H"][self.round % 4]
                    value = await self.request(
                        "POST",
                        "/data/history/jobs",
                        json={
                            "codes": [
                                "601398.SH",
                                "600519.SH",
                                "601318.SH",
                                "600036.SH",
                                "600000.SH",
                                "601288.SH",
                                "601988.SH",
                                "000001.SZ",
                                "000002.SZ",
                                "000333.SZ",
                            ],
                            "start_date": "2021-11-14",
                            "end_date": "2026-11-13",
                            "interval": interval,
                        },
                    )
                    self.current = value["id"]
                    self.round += 1
                    self.record("history_created", job=self.current, interval=interval, chunks=value["total_chunks"])
                jobs = await self.request("GET", "/data/history/jobs")
                state = next(row for row in jobs if row["id"] == self.current)
                if state["state"] == "complete":
                    self.completed.append(state)
                    self.record("history_complete", **state)
                    # Exercise the actual bounded page endpoint, retaining no prices.
                    for offset in (0, max(0, state["rows"] // 2), max(0, state["rows"] - 1000)):
                        stamp = time.monotonic()
                        page = await self.request(
                            "GET", f"/data/history/jobs/{self.current}/rows", params={"offset": offset, "limit": 1000}
                        )
                        self.record(
                            "history_page",
                            job=self.current,
                            offset=offset,
                            rows=len(page["rows"]),
                            latency_ms=round((time.monotonic() - stamp) * 1000, 3),
                        )
                    self.current = None
                elif state["state"] in {"failed", "paused", "interrupted"}:
                    metrics = await self.request("GET", "/_soak/metrics")
                    if metrics["fault"] != "all_offline":
                        self.record(
                            "history_resume",
                            job=self.current,
                            completed_chunks=state["completed_chunks"],
                            error=state.get("error"),
                        )
                        await self.request("POST", f"/data/history/jobs/{self.current}/resume")
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
        except Exception as exc:
            self.error = type(exc).__name__ + ": " + str(exc)[:240]
            self.record("history_driver_error", error=self.error)
            raise

    async def finish(self, task):
        self.stop.set()
        await task
        if self.current:
            await self.request("POST", f"/data/history/jobs/{self.current}/cancel")
            # Cancellation is between chunks; wait for the real worker to release.
            for _ in range(45):
                jobs = await self.request("GET", "/data/history/jobs")
                state = next(row for row in jobs if row["id"] == self.current)
                if state["state"] not in {"running", "queued"}:
                    self.record("history_stopped", **state)
                    break
                await asyncio.sleep(1)
            else:
                raise RuntimeError("History worker did not stop within 45 seconds")
