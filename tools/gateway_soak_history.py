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

    def __init__(self, client, url, checks, started, routed=False):
        self.client, self.url, self.checks, self.started = client, url, checks, started
        self.stop = asyncio.Event()
        self.current = None
        self.completed = []
        self.error = None
        self.round = 0
        self.routed = routed
        self.route_round = 0
        self.next_route = 0

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
                if self.routed and time.monotonic() >= self.next_route:
                    await self.route_workload()
                    self.next_route = time.monotonic() + 120
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

    async def route_workload(self):
        """Time-share the single history worker through real pause/resume APIs."""
        parent = self.current
        await self.request("POST", f"/data/history/jobs/{parent}/cancel")
        for _ in range(45):
            state = await self.request("GET", f"/data/history/jobs/{parent}")
            if state["state"] not in {"running", "queued"}:
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError("History did not yield to routed job")
        specs = [
            {"codes": ["AAPL.US", "MSFT.US"], "start_date": "2021-11-14", "end_date": "2026-11-13", "interval": "1M"},
            {"codes": ["BTC-USDT", "ETH-USDT"], "start_date": "2026-11-12", "end_date": "2026-11-12", "interval": "1m"},
            {
                "codes": ["00700.HK", "TD.TO", "VOD.L"],
                "start_date": "2026-11-02",
                "end_date": "2026-11-13",
                "interval": "1D",
            },
            {"codes": ["AAPL.US", "MSFT.US"], "start_date": "2026-11-09", "end_date": "2026-11-13", "interval": "1m"},
        ]
        spec = {**specs[self.route_round % len(specs)], "source": "auto"}
        self.route_round += 1
        started = time.monotonic()
        value = await self.request("POST", "/data/history/jobs", json=spec)
        job = value["id"]
        await self.request("POST", f"/data/history/jobs/{job}/resume")
        recoveries, retry_at = [], 0.0
        while time.monotonic() - started < 90 and not self.stop.is_set():
            value = await self.request("GET", f"/data/history/jobs/{job}")
            if value["state"] in {"complete", "downloaded"}:
                break
            if value["state"] in {"failed", "paused", "interrupted"} and time.monotonic() >= retry_at:
                metrics = await self.request("GET", "/_soak/metrics")
                if metrics["fault"] != "all_offline":
                    recoveries.append({"error": value.get("error"), "completed_chunks": value["completed_chunks"]})
                    await self.request("POST", f"/data/history/jobs/{job}/resume")
                    retry_at = time.monotonic() + 10
            await asyncio.sleep(1)
        if value["state"] in {"running", "queued"}:
            await self.request("POST", f"/data/history/jobs/{job}/cancel")
            for _ in range(45):
                value = await self.request("GET", f"/data/history/jobs/{job}")
                if value["state"] not in {"running", "queued"}:
                    break
                await asyncio.sleep(1)
        self.record(
            "routed_history",
            recoveries=recoveries,
            spec=spec,
            state=value["state"],
            rows=value["rows"],
            chunks=value["completed_chunks"],
            total_chunks=value["total_chunks"],
            sources=sorted(
                {c.get("meta", {}).get("source", "unknown") for c in value.get("chunks", []) if c.get("meta")}
            ),
            error=value.get("error"),
            latency_ms=round((time.monotonic() - started) * 1000, 3),
        )
        # Read production pages on success; release these small test datasets so
        # an extended scan cannot exhaust the unchanged 32-dataset job bound.
        if value["state"] in {"complete", "downloaded"}:
            page = await self.request("GET", f"/data/history/jobs/{job}/rows", params={"limit": 1000})
            if not page["rows"] or page.get("sampled"):
                raise RuntimeError("Routed dataset page is empty or sampled")
        await self.request("DELETE", f"/data/history/jobs/{job}")
        if not self.stop.is_set():
            await self.request("POST", f"/data/history/jobs/{parent}/resume")

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
