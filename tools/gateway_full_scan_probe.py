"""One full-universe scan with ten real history jobs, streams and OS memory.

Uses the v21 server instrumentation without its restart/hold fault. Resource
limits and production deadlines come from defaults; only paths are overridden.
"""

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from gateway_soak_observer import Usage
from gateway_ten_job_restart_probe import SYMBOLS, server, verify_prefixes


def memory_tree(pid):
    """Read parent and descendants independently through the macOS OS API."""
    lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    rows, pending, seen = [], [pid], set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        usage = Usage()
        if lib.proc_pid_rusage(current, 4, ctypes.byref(usage)) != 0:
            continue
        rows.append({"pid": current, "rss_bytes": usage.values[6], "footprint_bytes": usage.values[7],
                     "peak_footprint_bytes": usage.values[28]})
        children = (ctypes.c_int * 64)()
        count = lib.proc_listchildpids(current, children, ctypes.sizeof(children))
        pending.extend(p for p in list(children)[:max(0, count)] if p > 0)
    return {"processes": rows, "tree_rss_bytes": sum(r["rss_bytes"] for r in rows),
            "tree_footprint_bytes": sum(r["footprint_bytes"] for r in rows)}


async def exercise(args):
    """Drive production HTTP routes and retain diagnostic metadata outside Git."""
    import httpx

    root = args.root
    root.mkdir(parents=True, exist_ok=False)
    universe_bytes = args.universe.read_bytes()
    universe = json.loads(universe_bytes)
    codes = universe["codes"]
    assert len(codes) == len(set(codes)) == 5224
    env = {k: v for k, v in os.environ.items() if not k.startswith("VIBE_GATEWAY_")}
    env.update(VIBE_GATEWAY_HISTORY_DIR=str(root / "history"), VIBE_GATEWAY_CACHE_DIR=str(root / "cache"),
               VIBE_TRADING_DATA_CACHE="0", VIBE_TRADING_HOME=str(root / "runtime"))
    report = {"phase": "starting", "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "universe_sha256": hashlib.sha256(universe_bytes).hexdigest(), "total_symbols": len(codes),
              "streams": [], "job_ids": [], "history_terminal": {}, "errors": [], "limits_changed": False}
    (root / "universe.json").write_bytes(universe_bytes)
    child, feeds = None, []
    start = time.monotonic()
    samples = []
    scan = None
    stopped = False

    def save():
        report["elapsed_seconds"] = time.monotonic() - start
        temp = root / "report.tmp"
        temp.write_text(json.dumps(report, indent=2))
        temp.replace(root / "report.json")

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{args.port}", timeout=15) as client:
        async def request(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        async def feed(group):
            stats = {"topics": group, "events": 0, "websocket": 0, "errors": [], "last_event_seconds": None}
            report["streams"].append(stats)
            try:
                async with client.stream("GET", "/data/stream", params={"topics": ",".join(group)}, timeout=None) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            stats["events"] += 1
                            stats["websocket"] += int('"websocket"' in line)
                            stats["last_event_seconds"] = time.monotonic() - start
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                stats["errors"].append(type(exc).__name__ + ": " + str(exc))

        async def sample(phase):
            jobs = await request("GET", "/data/history/jobs")
            gateway = await request("GET", "/data/status")
            workers = await request("GET", "/_probe/workers")
            progress = await request("GET", f"/data/scans/{scan['id']}") if scan else None
            value = {"elapsed_seconds": time.monotonic() - start, "phase": phase, **memory_tree(child.pid),
                     "gateway": gateway, "workers": workers, "scan": progress,
                     "jobs": [{k: j.get(k) for k in ("id", "state", "completed_chunks", "rows", "error", "retry_count", "retry_at", "auto_resume")} for j in jobs],
                     "streams": [{"events": s["events"], "websocket": s["websocket"], "errors": list(s["errors"])} for s in report["streams"]]}
            assert gateway["limits"] == {"memory_bytes": 8 * 1024**2, "disk_bytes": 64 * 1024**2, "workers": 4, "pending": 16}
            assert workers["futures"] <= 4 and workers["peak"] <= 1 and workers["max_workers"] == 1
            assert gateway["cache"]["memory_bytes"] <= 8 * 1024**2 and gateway["cache"]["disk_bytes"] <= 64 * 1024**2
            for job in jobs:
                if job["state"] in {"complete", "failed", "paused"}:
                    report["history_terminal"].setdefault(job["id"], {"elapsed_seconds": value["elapsed_seconds"], **job})
            with (root / "samples.jsonl").open("a") as stream:
                stream.write(json.dumps(value) + "\n")
            samples.append(value)
            report.update(phase=phase, latest=value)
            save()
            return value

        async def stop_load():
            nonlocal stopped
            if stopped:
                return
            stopped = True
            for f in feeds:
                f.cancel()
            await asyncio.gather(*feeds, return_exceptions=True)
            if scan:
                state = await request("GET", f"/data/scans/{scan['id']}")
                if state["state"] not in {"complete", "partial", "cancelled"}:
                    await request("POST", f"/data/scans/{scan['id']}/cancel")
            for job in await request("GET", "/data/history/jobs"):
                if job["state"] != "complete":
                    await request("POST", f"/data/history/jobs/{job['id']}/cancel")

        try:
            with (root / "server.log").open("w") as log:
                child = subprocess.Popen([sys.executable, __file__, "--server", "--root", str(root), "--port", str(args.port)],
                                         env=env, stdout=log, stderr=subprocess.STDOUT)
            report["pid"] = child.pid
            save()
            for _ in range(100):
                if child.poll() is not None:
                    raise RuntimeError("Server exited during startup")
                try:
                    await request("GET", "/data/status")
                    break
                except httpx.TransportError:
                    await asyncio.sleep(0.25)
            else:
                raise RuntimeError("Server startup timeout")
            await sample("baseline")
            topics = ["crypto:BTC-USDT", "crypto:ETH-USDT"] + [f"bars:{c}:1D" for c in codes[:14]]
            feeds = [asyncio.create_task(feed(topics[i:i + 8])) for i in range(0, 16, 8)]
            for symbol in SYMBOLS:
                job = await request("POST", "/data/history/jobs", json={"codes": [symbol], "start_date": "2021-11-14",
                                    "end_date": "2026-11-13", "interval": "5m"})
                report["job_ids"].append(job["id"])
                await request("POST", f"/data/history/jobs/{job['id']}/resume")
            scan = await request("POST", "/data/scans", json={"codes": codes, "start_date": "2026-11-02",
                                 "end_date": "2026-11-13", "interval": "1D"})
            report["scan_id"] = scan["id"]
            report["scan_start_seconds"] = time.monotonic() - start
            while time.monotonic() - start < args.max_seconds:
                value = await sample("active")
                if value["scan"]["state"] in {"complete", "partial", "cancelled"}:
                    report["scan_final"] = value["scan"]
                    report["scan_end_seconds"] = value["elapsed_seconds"]
                    report["history_at_scan_end"] = value["jobs"]
                    break
                await asyncio.sleep(2)
            else:
                raise RuntimeError("Experiment wall-clock budget reached before scan terminal state")
            report["storage_at_scan_end"] = await request("GET", "/data/history/storage")
            assert report["storage_at_scan_end"]["quota_bytes"] == 256 * 1024**2
            await stop_load()
            idle_start = time.monotonic()
            while time.monotonic() - idle_start < args.idle_seconds:
                # Scan metadata expires after idle; keep its terminal snapshot.
                saved_scan, scan = scan, None
                try:
                    await sample("idle")
                finally:
                    scan = saved_scan
                await asyncio.sleep(2)
            report["storage_final"] = await request("GET", "/data/history/storage")
        except Exception as exc:
            report["errors"].append(type(exc).__name__ + ": " + str(exc))
            raise
        finally:
            if child and child.poll() is None:
                try:
                    await stop_load()
                except Exception as exc:
                    report["errors"].append("cleanup: " + repr(exc))
                child.terminate()
                try:
                    await asyncio.to_thread(child.wait, timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()
                    await asyncio.to_thread(child.wait)
                report["exit_code"] = child.returncode
            save()
    verified = await asyncio.to_thread(verify_prefixes, root)
    (root / "verification.json").write_text(json.dumps(verified, indent=2))
    traces = [json.loads(line) for line in (root / "scan-trace.jsonl").read_text().splitlines()]
    from gateway_full_scan_report import partition_bars

    batches, history_fallback = partition_bars(traces, report["scan_final"])
    missing = [t for t in batches if set(t["codes"]) != set(t["returned"]) or not t["ok"]]
    returned = {c for t in batches for c in t["returned"]}
    report.update(phase="complete", prefixes_verified=True, scan_identity_coverage=len(returned & set(codes)),
                  unreturned_codes=sorted(set(codes) - returned), missing_batches=missing,
                  completed_scan_requests=len(batches), historical_fallback_requests=len(history_fallback), max_scan_request_seconds=max(t["elapsed"] for t in batches),
                  full_scan_complete=report["scan_final"]["complete"] and returned >= set(codes),
                  passed=report["scan_final"]["complete"] and returned >= set(codes) and not missing
                  and report["scan_final"]["retries"] == 0 and not report["errors"]
                  and all(not s["errors"] for s in report["streams"]))
    save()
    print(json.dumps({k: report[k] for k in ("passed", "elapsed_seconds", "scan_final", "scan_identity_coverage", "max_scan_request_seconds")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--universe", type=Path)
    parser.add_argument("--port", type=int, default=8926)
    parser.add_argument("--max-seconds", type=float, default=14400)
    parser.add_argument("--idle-seconds", type=float, default=180)
    parser.add_argument("--server", action="store_true")
    args = parser.parse_args()
    if args.server:
        args.phase, args.hold = 0, 10**9
        server(args)
    else:
        asyncio.run(exercise(args))


if __name__ == "__main__":
    main()
