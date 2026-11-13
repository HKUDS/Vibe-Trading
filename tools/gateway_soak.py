"""Opt-in live gateway soak; run from the checkout with PYTHONPATH=agent.

Uses a dedicated child process and temporary cache, never the normal API's state.
Faults abort that child's actual upstream WebSockets and refuse new source calls;
this is transport-boundary fault injection, not a host-wide network outage.
Only operational metadata is saved. No quotes or credentials enter the report.
"""

import argparse
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
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


def process_memory():
    """Read current process RSS and macOS physical footprint from the OS."""
    if sys.platform == "darwin":

        class Usage(ctypes.Structure):
            _fields_ = [("uuid", ctypes.c_uint8 * 16), ("values", ctypes.c_uint64 * 18)]

        usage = Usage()
        lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        if lib.proc_pid_rusage(os.getpid(), 2, ctypes.byref(usage)) != 0:
            raise OSError(ctypes.get_errno(), "proc_pid_rusage failed")
        fds = ctypes.create_string_buffer(65536)
        count = lib.proc_pidinfo(os.getpid(), 1, 0, fds, len(fds))
        return {"rss_bytes": usage.values[6], "footprint_bytes": usage.values[7], "fds": count // 8}
    status = Path("/proc/self/status").read_text()
    rss = int(next(line.split()[1] for line in status.splitlines() if line.startswith("VmRSS:"))) * 1024
    return {"rss_bytes": rss, "footprint_bytes": None, "fds": len(os.listdir("/proc/self/fd"))}


def serve(port):
    """Run production routes with test-only instrumentation on loopback."""
    import uvicorn
    import websockets.asyncio.client as ws_client
    from fastapi import FastAPI, Query
    from src.data_gateway import get_gateway
    from src.data_gateway import api, streams

    original_connect = ws_client.connect
    original_snapshot = streams.okx_snapshot
    sockets = set()
    counts = Counter()
    fault = {"mode": "online"}
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
    original_invoke = gateway.invoke

    def invoke(function, params, timeout):
        counts["source_attempts"] += 1
        if fault["mode"] == "all_offline":
            counts["source_refused"] += 1
            raise ConnectionError("soak injected network unavailable")
        return original_invoke(function, params, timeout)

    gateway.invoke = invoke

    @asynccontextmanager
    async def lifespan(app):
        yield
        gateway.close()

    app = FastAPI(lifespan=lifespan)
    api.register_gateway_routes(app, lambda: None)

    @app.post("/_soak/fault")
    async def set_fault(mode: str = Query(pattern="^(online|ws_offline|all_offline)$")):
        fault["mode"] = mode
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
            "subscriptions": hubs[0].status() if hubs else {"clients": 0, "topics": [], "pending_updates": 0},
        }

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


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

    def save():
        document = {
            "started_utc": started_utc,
            "elapsed_s": round(time.monotonic() - started, 2),
            "phase": phase,
            "samples": samples,
            "transitions": transitions,
            "checks": checks,
            "counts": dict(counts),
            "topics": observed,
            "method": "real upstreams; child-only socket abort/source-refusal faults; no forced GC; default gateway limits",
        }
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, indent=2))
        temporary.replace(output)

    async with httpx.AsyncClient(timeout=25, limits=httpx.Limits(max_connections=16)) as client:
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
            try:
                async with client.stream(
                    "GET", url + "/data/stream", params={"topics": ",".join(topics)}, timeout=None
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
            response = await client.post(url + "/data/bars", json=body)
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
                    "cycle": current_cycle,
                    "status": response.status_code,
                    "ok": value.get("ok"),
                    "complete": value.get("complete"),
                    "request": body,
                    "shape": shape,
                    "diagnostics": value.get("data", {}).get("_diagnostics"),
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
        try:
            chain = (await client.get(url + "/data/options", params={"ticker": "AAPL", "full": "true"})).json()
            dates = chain.get("data", {}).get("expirations", [])
            checks.append({"kind": "expiration_discovery", "ok": chain.get("ok"), "count": len(dates)})
            if len(dates) > 1:
                expiry_topic = f"options:AAPL:{dates[1]}"
                base.append(asyncio.create_task(stream([expiry_topic])))
            if len(dates) > 2:
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
            for group in groups:
                active = [asyncio.create_task(stream(group))]
                await pause(args.warmup / len(groups))
                await stop(active)
            await client.post(url + "/_soak/slow", params={"enabled": "true"})
            active_started = time.monotonic()
            churn_task = asyncio.create_task(churn(active_started + args.cycles * args.cycle_seconds))
            for current_cycle in range(args.cycles):
                phase = "online"
                active = [asyncio.create_task(stream(groups[current_cycle % len(groups)]))]
                await set_fault("online")
                await pause(args.cycle_seconds * 0.25)
                if prior_fault_probe is not None:
                    await bar_probe("recovered_bar_probe", prior_fault_probe)
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
        finally:
            await set_fault("online")
            await stop(base)
            await client.post(url + "/_soak/slow", params={"enabled": "false"})
        phase = "idle"
        await pause(args.idle)
        await sample()
        phase = "complete"
        save()
        print(
            json.dumps({"phase": phase, "report": str(output), "elapsed_s": round(time.monotonic() - started, 2)}),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vibe-gateway-soak-cache-") as directory:
        environment = dict(os.environ, VIBE_GATEWAY_CACHE_DIR=directory)
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
