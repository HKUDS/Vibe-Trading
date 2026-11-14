"""Opt-in live gateway soak; run from the checkout with PYTHONPATH=agent.

Uses a dedicated child process and temporary cache, never the normal API's state.
Faults abort that child's actual upstream WebSockets and refuse new source calls;
this is transport-boundary fault injection, not a host-wide network outage.
Only operational metadata is saved. No quotes or credentials enter the report.
"""

import argparse
import asyncio
from collections import Counter, deque
from gateway_soak_history import Timings, HistoryDriver, instrument_history, abort_history
from contextlib import asynccontextmanager
from contextvars import ContextVar
import ctypes
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time


class _Usage(ctypes.Structure):
    _fields_ = [("uuid", ctypes.c_uint8 * 16), ("values", ctypes.c_uint64 * 35)]


_LIBPROC = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True) if sys.platform == "darwin" else None


def process_memory():
    """Read whole-process current/lifetime peak physical memory from the OS."""
    if _LIBPROC is not None:
        usage = _Usage()
        if _LIBPROC.proc_pid_rusage(os.getpid(), 4, ctypes.byref(usage)) != 0:
            raise OSError(ctypes.get_errno(), "proc_pid_rusage failed")
        fds = ctypes.create_string_buffer(65536)
        count = _LIBPROC.proc_pidinfo(os.getpid(), 1, 0, fds, len(fds))
        return {
            "rss_bytes": usage.values[6],
            "footprint_bytes": usage.values[7],
            "peak_footprint_bytes": usage.values[28],
            "fds": count // 8,
            "cpu_seconds": (usage.values[0] + usage.values[1]) / 1e9,
        }
    status = Path("/proc/self/status").read_text()
    rss = int(next(line.split()[1] for line in status.splitlines() if line.startswith("VmRSS:"))) * 1024
    return {"rss_bytes": rss, "footprint_bytes": None, "fds": len(os.listdir("/proc/self/fd"))}


def serve(port):
    """Run production routes with test-only instrumentation on loopback."""
    import uvicorn
    import gc
    import tracemalloc
    import faulthandler

    faulthandler.enable()

    trace_dir = os.environ.get("VIBE_GATEWAY_TRACE_DIR")
    trace_baseline = None
    import websockets.asyncio.client as ws_client
    from fastapi import FastAPI, Query
    from src.data_gateway import get_gateway
    from src.data_gateway import api, streams

    original_connect = ws_client.connect
    original_snapshot = streams.okx_snapshot
    sockets = set()
    counts = Counter()
    fault = {"mode": "online", "epoch": 0}
    timings = Timings()
    history = instrument_history(fault, counts, timings) if os.getenv("VIBE_GATEWAY_SOAK_HISTORY") else None
    hubs = []
    slow = []

    @asynccontextmanager
    async def controlled_connect(*args, **kwargs):
        counts["ws_attempts"] += 1
        if fault["mode"] != "online":
            counts["ws_refused"] += 1
            raise ConnectionError("soak injected connection failure")
        async with original_connect(*args, **kwargs) as socket:
            if fault["mode"] != "online":
                socket.transport.abort()
                counts["ws_refused_after_handshake"] += 1
                raise ConnectionError("soak fault changed during handshake")
            sockets.add(socket)
            counts["ws_connected"] += 1
            try:
                yield socket
            finally:
                sockets.discard(socket)
                counts["ws_closed"] += 1

    async def snapshot(topic):
        counts["rest_attempts"] += 1
        if fault["mode"] == "all_offline":
            counts["rest_refused"] += 1
            raise ConnectionError("soak injected network unavailable")
        value = await original_snapshot(topic)
        if fault["mode"] == "all_offline":
            counts["rest_refused_after_response"] += 1
            raise ConnectionError("soak fault changed during REST response")
        counts["rest_success"] += 1
        return value

    ws_client.connect = controlled_connect
    original_hub = streams.StreamHub

    async def feed(topic, publish):
        def guarded_publish(event, value):
            if fault["mode"] == "online":
                counts["ws_live_events"] += 1
                publish(event, value)
            else:
                counts["ws_buffered_events_dropped"] += 1

        await streams.okx_feed(topic, guarded_publish)

    def make_hub(gateway):
        hub = original_hub(gateway, crypto_feed=feed, snapshot_feed=snapshot)
        hubs.append(hub)
        return hub

    api.StreamHub = make_hub
    gateway = get_gateway()
    # Request-scoped metadata only. Context is copied into the production
    # coordinator/source pools; completed traces are not kept in a global list.
    request_trace = ContextVar("soak_request_trace", default=None)
    trace_lock = threading.Lock()
    original_request, original_fetch = gateway.request, gateway._fetch

    def trace_event(stage):
        trace = request_trace.get()
        if trace is not None:
            with trace_lock:
                if len(trace["events"]) < 64:
                    trace["events"].append([stage, round(time.monotonic() - trace["started"], 4)])
                else:
                    trace["events_truncated"] = True

    def emit_trace(trace, reason):
        with trace_lock:
            record = {k: v for k, v in trace.items() if k not in {"started", "reported"}}
            record["events"] = list(trace["events"])
        print(json.dumps({"slow_gateway_request": reason, **record}), flush=True)

    def traced_request(capability, params, **kwargs):
        trace = {
            "started": time.monotonic(),
            "request_id": time.monotonic_ns(),
            "capability": capability,
            "params": {
                k: v
                for k, v in params.items()
                if k in {"codes", "ticker", "expiration", "interval", "source", "start_date", "end_date", "max_rows"}
            },
            "events": [],
            "reported": False,
        }
        token = request_trace.set(trace)
        try:
            value = original_request(capability, params, **kwargs)
            trace_event("caller_return")
            if time.monotonic() - trace["started"] >= 12 or "timed out" in str(value.get("error", "")):
                with trace_lock:
                    trace["reported"] = True
                    trace["error"] = value.get("error")
                emit_trace(trace, "caller_return")
            return value
        finally:
            request_trace.reset(token)

    def traced_fetch(*args):
        trace_event("coordinator_start")
        try:
            return original_fetch(*args)
        finally:
            trace_event("coordinator_end")
            trace = request_trace.get()
            if trace and trace["reported"]:
                emit_trace(trace, "late_coordinator_end")

    gateway.request, gateway._fetch = traced_request, traced_fetch
    original_submit_source = gateway.submit_source

    def submit_source(function, params, timeout, **admission):
        if fault["mode"] == "all_offline":
            counts["source_refused"] += 1
            raise ConnectionError("soak injected network unavailable")
        submitted = time.monotonic()
        original_admit = admission.get("admit")

        def admit():
            if original_admit is not None and not original_admit():
                return False
            trace_event("source_submit")
            return True

        admission["admit"] = admit

        def measured(**kwargs):
            stamp = time.monotonic()
            trace_event("source_start")
            timings.add("source_queue", stamp - submitted)
            try:
                result = function(**kwargs)
            except Exception:
                trace_event("source_failed")
                timings.add("source_failed", time.monotonic() - stamp)
                raise
            trace_event("source_success")
            timings.add("source_success", time.monotonic() - stamp)
            return result

        future = original_submit_source(measured, params, timeout, **admission)
        counts["source_attempts"] += 1
        return future

    gateway.submit_source = submit_source

    pending_http = {}
    monitor_stop = threading.Event()

    def watchdog():
        while not monitor_stop.wait(1):
            now = time.monotonic()
            for row in list(pending_http.values()):
                if now - row["started"] >= 12 and not row["dumped"]:
                    row["dumped"] = True
                    print(
                        json.dumps(
                            {"slow_request": row["path"], "seconds": now - row["started"], "load": os.getloadavg()}
                        ),
                        flush=True,
                    )
                    faulthandler.dump_traceback()

    async def heartbeat():
        while True:
            stamp = time.monotonic()
            await asyncio.sleep(0.25)
            timings.add("event_loop_lag", max(0, time.monotonic() - stamp - 0.25))

    @asynccontextmanager
    async def lifespan(app):
        monitor = threading.Thread(target=watchdog, daemon=True, name="soak-watchdog")
        monitor.start()
        beat = asyncio.create_task(heartbeat())
        try:
            yield
        finally:
            beat.cancel()
            await asyncio.gather(beat, return_exceptions=True)
            monitor_stop.set()
            monitor.join(timeout=2)
        gateway.close()
        if history:
            history.close()

    app = FastAPI(lifespan=lifespan)
    api.register_gateway_routes(app, lambda: None)

    @app.post("/_soak/trace")
    async def trace(label: str, collect: bool = False):
        nonlocal trace_baseline
        if not trace_dir:
            return {"enabled": False}
        if not tracemalloc.is_tracing():
            tracemalloc.start(1)
        if collect:
            gc.collect()  # Diagnostic control only; never used by production.
        current = tracemalloc.take_snapshot()
        objects = gc.get_objects()
        kinds = Counter(str(type(obj).__module__) + "." + str(type(obj).__name__) for obj in objects)
        del objects
        result = {
            **process_memory(),
            "label": label,
            "collected": collect,
            "python_bytes": tracemalloc.get_traced_memory()[0],
            "threads": [thread.name for thread in threading.enumerate()],
            "types": kinds.most_common(60),
            "growth": [
                {"trace": str(row.traceback), "bytes": row.size_diff, "count": row.count_diff}
                for row in (current.compare_to(trace_baseline, "lineno")[:30] if trace_baseline else [])
            ],
        }
        if trace_baseline is None:
            trace_baseline = current
        destination = Path(trace_dir)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / (label + ".json")).write_text(json.dumps(result, indent=2))
        return {"enabled": True, "label": label, "python_bytes": result["python_bytes"]}

    @app.post("/_soak/fault")
    async def set_fault(mode: str = Query(pattern="^(online|ws_offline|all_offline)$")):
        fault["mode"] = mode
        if mode == "all_offline":
            fault["epoch"] += 1
            if history:
                abort_history(counts)
        if mode != "online":
            for socket in list(sockets):
                socket.transport.abort()
                counts["ws_aborted"] += 1
        return dict(fault)

    @app.post("/_soak/slow")
    async def slow_client(enabled: bool):
        if enabled and hubs and not slow:
            slow.append(
                hubs[0].subscribe([streams.Topic.parse("crypto:BTC-USDT"), streams.Topic.parse("options:AAPL")])
            )
        elif not enabled:
            for listener in slow:
                await hubs[0].unsubscribe(listener)
            slow.clear()
        return {"slow_clients": len(slow)}

    @app.get("/_soak/metrics")
    async def metrics():
        return {
            **process_memory(),
            "pid": os.getpid(),
            "threads": threading.active_count(),
            "async_tasks": len(asyncio.all_tasks()),
            "sockets": len(sockets),
            "counts": dict(counts),
            "fault": fault["mode"],
            "gateway": await asyncio.to_thread(gateway.status),
            "history": await asyncio.to_thread(history.status) if history else [],
            "history_storage": await asyncio.to_thread(history.settings) if history else None,
            "timings": timings.summary(),
            "subscriptions": hubs[0].status() if hubs else {"clients": 0, "topics": [], "pending_updates": 0},
        }

    async def measured_app(scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/data/stream":
            return await app(scope, receive, send)
        key = id(scope)
        row = {"path": scope["path"], "started": time.monotonic(), "dumped": False}
        pending_http[key] = row
        try:
            return await app(scope, receive, send)
        finally:
            pending_http.pop(key, None)
            # Group paths, never retain unbounded job IDs.
            group = "/".join(scope["path"].split("/")[:3])
            timings.add("http:" + group, time.monotonic() - row["started"])

    uvicorn.run(measured_app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


async def exercise(args, output):
    """Drive repeated live subscriptions and retain only bounded event summaries."""
    import httpx

    started = time.monotonic()
    started_utc = datetime.now(timezone.utc).isoformat()
    url = f"http://127.0.0.1:{args.port}"
    samples, transitions, checks = [], [], []
    counts = Counter()
    observed = {}
    phase = "startup"
    current_cycle = -1
    history_driver = None
    history_task = None
    active_started = None
    active_finished = None

    def save():
        document = {
            "started_utc": started_utc,
            "active_elapsed_s": round((active_finished or time.monotonic()) - active_started, 2)
            if active_started
            else 0,
            "history_enabled": args.history,
            "scale_universe": scale_universe,
            "scan_job": scan_job,
            "history_directory": str(args.history_dir) if args.history else None,
            "elapsed_s": round(time.monotonic() - started, 2),
            "phase": phase,
            "samples": samples,
            "transitions": transitions,
            "checks": checks,
            "counts": dict(counts),
            "topics": observed,
            "method": "real upstreams; child-only socket abort/source-refusal faults; no forced GC; unchanged workers/pending/cache budgets; topic cap 64 only when --universe is supplied",
        }
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, indent=2))
        temporary.replace(output)

    scale_universe = json.loads(args.universe.read_text()) if args.universe else None
    scan_job = None
    async with httpx.AsyncClient(timeout=25, limits=httpx.Limits(max_connections=16, keepalive_expiry=2)) as client:
        for _ in range(120):
            try:
                await client.get(url + "/_soak/metrics")
                break
            except httpx.TransportError:
                await asyncio.sleep(1)
        else:
            raise RuntimeError("Soak child did not start")

        async def stream(topics, hold=None):
            counts["subscribes"] += 1
            trace_events = deque(maxlen=24)

            async def trace(name, info):
                trace_events.append(
                    {
                        "event": name,
                        "elapsed_s": round(time.monotonic() - started, 4),
                        "exception": repr(info.get("exception"))[:160] if "exception" in info else None,
                    }
                )

            try:
                async with client.stream(
                    "GET",
                    url + "/data/stream",
                    params={"topics": ",".join(topics)},
                    timeout=None,
                    extensions={"trace": trace},
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            value = json.loads(line[6:])
                            payload = value.get("payload", {})
                            topic = value["topic"]
                            row = observed.setdefault(
                                topic,
                                {
                                    "snapshots": 0,
                                    "errors": 0,
                                    "transports": {},
                                    "qualities": {},
                                    "first_s": round(time.monotonic() - started, 2),
                                },
                            )
                            event = value["event"]
                            row["snapshots" if event == "snapshot" else "errors"] += 1
                            if event != "snapshot":
                                reasons = row.setdefault("error_reasons", {})
                                reason = (phase + ":" + str(payload.get("error", "unknown")))[:160]
                                if len(reasons) >= 16 and reason not in reasons:
                                    reason = "other"
                                reasons[reason] = reasons.get(reason, 0) + 1
                            fetched = payload.get("gateway", {}).get("fetched_at")
                            if event == "snapshot" and fetched and fetched != row.get("last_fetched_at"):
                                previous = row.get("last_fetched_at")
                                if previous:
                                    gap = (
                                        datetime.fromisoformat(fetched) - datetime.fromisoformat(previous)
                                    ).total_seconds()
                                    row["max_acquisition_gap_seconds"] = max(
                                        row.get("max_acquisition_gap_seconds", 0), round(gap, 3)
                                    )
                                    row["acquisition_gaps_over_180s"] = row.get("acquisition_gaps_over_180s", 0) + int(
                                        gap > 180
                                    )
                                row["distinct_acquisitions"] = row.get("distinct_acquisitions", 0) + 1
                                row["last_fetched_at"] = fetched
                            row["last_s"] = round(time.monotonic() - started, 2)
                            transport = payload.get("gateway", {}).get("transport", "snapshot")
                            row["transports"][transport] = row["transports"].get(transport, 0) + 1
                            quality = payload.get("gateway", {}).get("quality", "unspecified")
                            row["qualities"][quality] = row["qualities"].get(quality, 0) + 1
                            row.setdefault("sources", {})[payload.get("source", "none")] = True
                            if event == "snapshot" and topic.startswith("bars:"):
                                symbol = topic.split(":")[1]
                                rows = payload.get("data", {}).get(symbol, [])
                                row["bar_shape"] = {
                                    "rows": len(rows) if isinstance(rows, list) else rows.get("rows"),
                                    "sampled": isinstance(rows, dict),
                                }
                            if transitions and event == "snapshot":
                                transition = transitions[-1]
                                key = f"{topic}:{transport}"
                                transition.setdefault("first_snapshot_after", {}).setdefault(
                                    key, round(time.monotonic() - started - transition["elapsed_s"], 2)
                                )
                            counts[event] += 1
                            counts[f"phase:{phase}:{event}:{transport}"] += 1
                            if hold:
                                await asyncio.sleep(hold)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                counts[f"client_error:{type(exc).__name__}"] += 1
                checks.append(
                    {
                        "kind": "client_error",
                        "elapsed_s": round(time.monotonic() - started, 2),
                        "topics": topics,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:200],
                        "cause_type": type(exc.__cause__).__name__ if exc.__cause__ else None,
                        "trace": list(trace_events),
                        "cancel_requested": bool(asyncio.current_task().cancelling()),
                        "phase": phase,
                    }
                )
            finally:
                counts["unsubscribes"] += 1

        async def stop(tasks):
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            tasks.clear()

        async def set_fault(mode):
            response = await client.post(url + "/_soak/fault", params={"mode": mode})
            response.raise_for_status()
            transitions.append(
                {"elapsed_s": round(time.monotonic() - started, 2), "mode": mode, "cycle": current_cycle}
            )

        async def sample():
            nonlocal scan_job
            response = await client.get(url + "/_soak/metrics")
            response.raise_for_status()
            samples.append(
                {
                    "elapsed_s": round(time.monotonic() - started, 2),
                    "phase": phase,
                    "cycle": current_cycle,
                    **response.json(),
                }
            )
            if phase != "idle":
                current_time = datetime.now(timezone.utc)
                for row in observed.values():
                    if row.get("last_fetched_at"):
                        age = max(0, (current_time - datetime.fromisoformat(row["last_fetched_at"])).total_seconds())
                        row["max_observed_acquisition_age_seconds"] = max(
                            row.get("max_observed_acquisition_age_seconds", 0), round(age, 3)
                        )
            for job in response.json()["gateway"].get("scans", []):
                if scan_job and job["id"] == scan_job["id"]:
                    scan_job = job
            save()

        async def pause(seconds):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                await sample()
                await asyncio.sleep(min(10, max(0, end - time.monotonic())))

        async def churn(deadline):
            while time.monotonic() < deadline:
                tasks = [asyncio.create_task(stream(["crypto:BTC-USDT", "options:AAPL"])) for _ in range(2)]
                await asyncio.sleep(3)
                await stop(tasks)
                await asyncio.sleep(2)

        async def bar_probe(label, body):
            stamp = time.monotonic()
            response = await client.post(url + "/data/bars", json=body)
            latency_ms = round((time.monotonic() - stamp) * 1000, 3)
            value = response.json()
            shape = {}
            for symbol in body["codes"]:
                rows = value.get("data", {}).get(symbol, [])
                shape[symbol] = {
                    "rows": len(rows) if isinstance(rows, list) else rows.get("rows"),
                    "sampled": isinstance(rows, dict),
                }
            checks.append(
                {
                    "kind": label,
                    "latency_ms": latency_ms,
                    "elapsed_s": round(time.monotonic() - started, 2),
                    "cycle": current_cycle,
                    "status": response.status_code,
                    "ok": value.get("ok"),
                    "complete": value.get("complete"),
                    "request": body,
                    "shape": shape,
                    "provenance": value.get("data", {}).get("_provenance"),
                    "diagnostics": value.get("data", {}).get("_diagnostics"),
                    "recovery": value.get("data", {}).get("_recovery"),
                    "retry_after_seconds": value.get("retry_after_seconds"),
                    "gateway": value.get("gateway"),
                    "error": value.get("error"),
                }
            )

        async def mixed_cold_probes():
            # Distinct bounded preview sizes ensure cold identities each round.
            end = today - timedelta(days=1)
            minute_day = end
            while minute_day.weekday() >= 5:
                minute_day -= timedelta(days=1)
            shapes = [
                (
                    "mixed_cold_six_markets",
                    ["AAPL.US", "00700.HK", "TD.TO", "VOD.L", "601398.SH", "BTC-USDT"],
                    end - timedelta(days=29),
                    end,
                    "1D",
                    700,
                ),
                ("mixed_cold_five_year_monthly", ["AAPL.US", "MSFT.US"], end - timedelta(days=1825), end, "1M", 800),
                (
                    "mixed_cold_us_minutes",
                    ["AAPL.US", "MSFT.US"],
                    minute_day - timedelta(days=1),
                    minute_day - timedelta(days=1),
                    "1m",
                    900,
                ),
            ]
            await asyncio.gather(
                *(
                    bar_probe(
                        label,
                        {
                            "codes": codes,
                            "start_date": str(start),
                            "end_date": str(end_date),
                            "interval": interval,
                            "max_rows": base + current_cycle,
                        },
                    )
                    for label, codes, start, end_date, interval, base in shapes
                )
            )

        async def latency_probe():
            choices = [("BTC-USDT", "5m", 5), ("AAPL.US", "1D", 365), ("00700.HK", "1D", 365), ("601398.SH", "1D", 365)]
            code, interval, days = choices[current_cycle % len(choices)]
            body = {
                "codes": [code],
                "interval": interval,
                "start_date": str(today - timedelta(days=days)),
                "end_date": str(today),
                "max_rows": 500 + current_cycle,
            }
            await bar_probe("latency_first_bar", body)
            await bar_probe("latency_repeat_bar", body)
            for repeat in (False, True):
                stamp = time.monotonic()
                response = await client.get(
                    url + "/data/options", params={"ticker": "AAPL", "full": "true", "allow_stale": "false"}
                )
                value = response.json()
                checks.append(
                    {
                        "kind": "latency_repeat_options" if repeat else "latency_first_options",
                        "cycle": current_cycle,
                        "elapsed_s": round(time.monotonic() - started, 2),
                        "latency_ms": round((time.monotonic() - stamp) * 1000, 3),
                        "status": response.status_code,
                        "ok": value.get("ok"),
                        "source": value.get("source"),
                        "gateway": value.get("gateway"),
                        "error": value.get("error"),
                    }
                )

        # Warm every data shape before comparing repeated steady-state cycles.
        phase = "warmup"
        base = [asyncio.create_task(stream(["crypto:BTC-USDT", "crypto:ETH-USDT", "options:AAPL", "options:SPY"]))]
        intervals = ["1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"]
        groups = [[f"bars:BTC-USDT:{x}" for x in intervals[i : i + 3]] for i in range(0, 9, 3)]
        groups.append(["bars:AAPL.US:1D", "bars:00700.HK:1D", "bars:601398.SH:1D"])
        expiry_topic = None
        failure = None
        try:
            chain = (await client.get(url + "/data/options", params={"ticker": "AAPL", "full": "true"})).json()
            dates = chain.get("data", {}).get("expirations", [])
            checks.append({"kind": "expiration_discovery", "ok": chain.get("ok"), "count": len(dates)})
            if not scale_universe and len(dates) > 1:
                expiry_topic = f"options:AAPL:{dates[1]}"
                base.append(asyncio.create_task(stream([expiry_topic])))
            if not scale_universe and len(dates) > 2:
                base.append(asyncio.create_task(stream([f"options:AAPL:{dates[-1]}"])))
            today = datetime.now(timezone.utc).date()
            for days, interval in ((2, "1m"), (365, "1D"), (1825, "1M")):
                await bar_probe(
                    "lookback",
                    {
                        "codes": ["BTC-USDT" if interval == "1m" else "AAPL.US"],
                        "start_date": str(today - timedelta(days=days)),
                        "end_date": str(today),
                        "interval": interval,
                        "max_rows": 1000,
                    },
                )
            prior_fault_probe = None
            if scale_universe:
                selected = scale_universe["codes"][:30]
                watched = [f"bars:{code}:{interval}" for code in selected for interval in ("1D", "1W")]
                for pos in range(0, len(watched), 8):
                    base.append(asyncio.create_task(stream(watched[pos : pos + 8])))
                await pause(args.warmup)
            for group in [] if scale_universe else groups:
                active = [asyncio.create_task(stream(group))]
                await pause(args.warmup / len(groups))
                await stop(active)
            await client.post(url + "/_soak/slow", params={"enabled": "true"})
            (await client.post(url + "/_soak/trace", params={"label": "warm"})).raise_for_status()
            active_started = time.monotonic()
            if scale_universe:
                response = await client.post(
                    url + "/data/scans",
                    json={
                        "codes": scale_universe["codes"],
                        "start_date": str(today - timedelta(days=30)),
                        "end_date": str(today),
                        "interval": "1D",
                        "max_rows": 100,
                    },
                )
                response.raise_for_status()
                scan_job = response.json()
            if args.history:
                history_driver = HistoryDriver(client, url, checks, started, routed=args.routed_history)
                history_task = asyncio.create_task(history_driver.run())
            churn_task = asyncio.create_task(churn(active_started + args.cycles * args.cycle_seconds))
            for current_cycle in range(args.cycles):
                phase = "online"
                active = [] if scale_universe else [asyncio.create_task(stream(groups[current_cycle % len(groups)]))]
                await set_fault("online")
                await pause(args.cycle_seconds * 0.25)
                if args.mixed_cold:
                    await mixed_cold_probes()
                if prior_fault_probe is not None:
                    await bar_probe("recovered_bar_probe", prior_fault_probe)
                    await bar_probe("hot_bar_probe", prior_fault_probe)
                await latency_probe()
                if scale_universe:
                    await bar_probe(
                        "heavy_sdk_probe",
                        {
                            "codes": ["BTC-USDT"],
                            "start_date": str(today - timedelta(days=13)),
                            "end_date": str(today - timedelta(days=1)),
                            "interval": "1D",
                            "source": "ccxt",
                            "max_rows": 100 + current_cycle,
                        },
                    )
                if history_task and history_task.done():
                    await history_task  # A dead producer must fail the test, not fake overlap.
                phase = "ws_offline"
                await set_fault("ws_offline")
                await pause(args.cycle_seconds * 0.25)
                phase = "recovered"
                await set_fault("online")
                await pause(args.cycle_seconds * 0.25)
                phase = "all_offline"
                await set_fault("all_offline")
                prior_fault_probe = {
                    "codes": ["BTC-USDT"],
                    "start_date": str(today - timedelta(days=20)),
                    "end_date": str(today),
                    "interval": "1D",
                    "max_rows": 80 + current_cycle,
                }
                await bar_probe("offline_bar_probe", prior_fault_probe)
                await pause(args.cycle_seconds * 0.15)
                phase = "recovered"
                await set_fault("online")
                await pause(args.cycle_seconds * 0.10)
                await stop(active)
                (await client.post(url + "/_soak/trace", params={"label": f"cycle-{current_cycle}"})).raise_for_status()
                print(
                    json.dumps(
                        {
                            "cycle": current_cycle + 1,
                            "rss_mib": round(samples[-1]["rss_bytes"] / 2**20, 2),
                            "footprint_mib": round((samples[-1]["footprint_bytes"] or 0) / 2**20, 2),
                            "subscriptions": counts["subscribes"],
                            "snapshots": counts["snapshot"],
                        }
                    ),
                    flush=True,
                )
            await churn_task
            if scan_job and scan_job["state"] in {"running", "queued"}:
                scan_job = (await client.get(url + "/data/scans/" + scan_job["id"])).json()
            if args.finish_scan and scan_job:
                phase = "scan_completion"
                until = time.monotonic() + args.scan_completion_timeout
                while scan_job["state"] in {"running", "queued"}:
                    if time.monotonic() >= until:
                        raise RuntimeError("Full scan completion deadline exceeded")
                    if history_task and history_task.done():
                        await history_task
                    await pause(10)
                    scan_job = (await client.get(url + "/data/scans/" + scan_job["id"])).json()
                checks.append({"kind": "scan_terminal", **scan_job})
            active_finished = time.monotonic()
        except BaseException as exc:
            active_finished = time.monotonic()
            failure = exc
            checks.append(
                {
                    "kind": "driver_error",
                    "type": type(exc).__name__,
                    "message": str(exc)[:200],
                    "elapsed_s": round(time.monotonic() - started, 2),
                }
            )
            phase = "failed"
            save()
            raise
        finally:

            async def cleanup(label, action):
                nonlocal phase
                try:
                    await action()
                except BaseException as exc:
                    checks.append(
                        {
                            "kind": "cleanup_error",
                            "action": label,
                            "type": type(exc).__name__,
                            "message": str(exc)[:200],
                            "elapsed_s": round(time.monotonic() - started, 2),
                        }
                    )
                    phase = "failed"
                    save()
                    if failure is None:
                        raise

            await cleanup("restore_online", lambda: set_fault("online"))
            await cleanup("stop_clients", lambda: stop(base))
            if scan_job and scan_job.get("state") in {"running", "queued"}:
                await cleanup("cancel_scan", lambda: client.post(url + "/data/scans/" + scan_job["id"] + "/cancel"))
            if history_driver:
                await cleanup("finish_history", lambda: history_driver.finish(history_task))
            await cleanup("stop_slow_client", lambda: client.post(url + "/_soak/slow", params={"enabled": "false"}))
        phase = "idle"
        await pause(args.idle)
        await sample()
        (await client.post(url + "/_soak/trace", params={"label": "idle"})).raise_for_status()
        (
            await client.post(url + "/_soak/trace", params={"label": "idle-collected", "collect": "true"})
        ).raise_for_status()
        phase = "complete"
        save()
        print(
            json.dumps({"phase": phase, "report": str(output), "elapsed_s": round(time.monotonic() - started, 2)}),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--universe", type=Path, help="Real universe JSON from gateway_scale_probe.universe; enables 64 topics + scan"
    )
    parser.add_argument(
        "--mixed-cold",
        action="store_true",
        help="Three concurrent cold market/horizon requests per online cycle, without retries",
    )
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--routed-history", action="store_true")
    parser.add_argument("--finish-scan", action="store_true")
    parser.add_argument("--scan-completion-timeout", type=float, default=7200)
    parser.add_argument("--history-dir", type=Path)
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--port", type=int, default=8911)
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--cycle-seconds", type=float, default=120)
    parser.add_argument("--warmup", type=float, default=180)
    parser.add_argument("--idle", type=float, default=180)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.server:
        serve(args.port)
        return
    if args.history and args.history_dir is None:
        parser.error("--history requires a fresh --history-dir outside the repository")
    if args.history and args.history_dir.exists():
        parser.error("--history-dir must be new so the run cannot reuse prior chunks")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vibe-gateway-soak-cache-") as directory:
        environment = dict(os.environ, VIBE_GATEWAY_CACHE_DIR=directory)
        if args.universe:
            environment["VIBE_GATEWAY_STREAM_TOPICS"] = "64"
        if args.history:
            environment.update(VIBE_GATEWAY_HISTORY_DIR=str(args.history_dir), VIBE_GATEWAY_SOAK_HISTORY="1")
        log = args.output.with_suffix(".server.log")
        with log.open("w") as handle:
            child = subprocess.Popen(
                [sys.executable, __file__, "--server", "--port", str(args.port), "--output", str(args.output)],
                env=environment,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
            try:
                asyncio.run(exercise(args, args.output))
            finally:
                child.terminate()
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    main()
