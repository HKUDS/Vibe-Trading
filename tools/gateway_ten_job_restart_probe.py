"""Short ten-job five-year 5m admission/fairness/restart probe with real sources.

The short test certifies committed prefixes, NOT all 610 planned chunks. Three
jobs are manually paused (running, executor-queued and catalog-waiting). Existing
16-topic streaming and full-universe scan load continue alongside acquisition.
"""

import argparse
import asyncio
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta
import gzip
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import subprocess
import sys
import time

from gateway_minute_restart_probe import snapshot

SYMBOLS = [
    "601398.SH",
    "600519.SH",
    "600036.SH",
    "600000.SH",
    "601318.SH",
    "600030.SH",
    "600276.SH",
    "000001.SZ",
    "000002.SZ",
    "000333.SZ",
]


def server(args):
    import uvicorn
    from src.data_gateway import history_router, history_store

    from src.data_gateway.service import MarketDataGateway
    from src.data_gateway.scheduling import background
    import threading

    trace_lock = threading.Lock()

    def trace(value):
        with trace_lock, (args.root / "scan-trace.jsonl").open("a") as stream:
            stream.write(json.dumps({"phase": args.phase, "time": time.time(), **value}) + "\n")

    original_bars = MarketDataGateway.bars
    original_submit = MarketDataGateway.submit_source

    def bars(self, **params):
        started = time.monotonic()
        value = original_bars(self, **params)
        if background.get():
            trace({"event": "bars", "codes": params["codes"], "elapsed": time.monotonic() - started,
                   "interval": params.get("interval", "1D"), "requested_source": params.get("source", "auto"),
                   "start_date": params.get("start_date"), "end_date": params.get("end_date"),
                   "ok": value.get("ok"), "error": value.get("error"),
                   "returned": list(value.get("data", {}).get("_provenance", {})),
                   "diagnostics": value.get("data", {}).get("_diagnostics", {})})
        return value

    def submit(self, function, params, timeout, **kwargs):
        defaults = getattr(function, "__defaults__", None)
        if defaults and len(defaults) >= 4 and isinstance(defaults[3], list):
            source, _, _, codes = defaults[:4]
            is_background = background.get()

            def traced(**arguments):
                started = time.monotonic()
                try:
                    result = function(**arguments)
                    trace({"event": "source", "source": source, "codes": codes,
                           "background": is_background, "elapsed": time.monotonic() - started,
                           "returned": list(result.get("_provenance", {})),
                           "diagnostics": result.get("_diagnostics", {})})
                    return result
                except Exception as exc:
                    trace({"event": "source", "source": source, "codes": codes,
                           "background": is_background, "elapsed": time.monotonic() - started,
                           "error": type(exc).__name__})
                    raise

            return original_submit(self, traced, params, timeout, **kwargs)
        return original_submit(self, function, params, timeout, **kwargs)

    MarketDataGateway.bars = bars
    MarketDataGateway.submit_source = submit
    original = history_router.fetch_chunk
    counters = {"active": 0, "peak": 0, "futures_peak": 0}
    held = False

    def record(value):
        with (args.root / "calls.jsonl").open("a") as stream:
            stream.write(json.dumps({"phase": args.phase, "time": time.time(), **value}) + "\n")

    def fetch(symbol, start, end, interval):
        nonlocal held
        counters["active"] += 1
        counters["peak"] = max(counters["peak"], counters["active"])
        counters["futures_peak"] = max(counters["futures_peak"], len(history_store._instance.futures))
        with closing(sqlite3.connect(args.root / "history/catalog.sqlite")) as db:
            already = bool(db.execute(
                "SELECT 1 FROM chunks WHERE symbol=? AND start=? AND end=? AND state='complete' LIMIT 1",
                (symbol, start, end),
            ).fetchone())
        identity = {"symbol": symbol, "start": start, "end": end}
        record({**identity, "event": "attempt", "already_complete": already})
        try:
            rows, meta = original(symbol, start, end, interval)
            record({**identity, "event": "acquired", "rows": len(rows)})
            with closing(sqlite3.connect(args.root / "history/catalog.sqlite")) as db:
                completed = db.execute("SELECT COUNT(*) FROM chunks WHERE state='complete'").fetchone()[0]
            if not held and completed >= args.hold:
                held = True
                (args.root / f"held-{args.phase}.json").write_text(json.dumps(identity))
                context = history_router.history_context.get() or {}
                while not context.get("stop_requested", lambda: False)():
                    time.sleep(0.05)
                raise history_router.HistoryPaused()
            return rows, meta
        finally:
            counters["active"] -= 1

    history_router.fetch_chunk = fetch
    from src.data_gateway.dev_server import app

    @app.get("/_probe/workers")
    async def workers():
        value = history_store._instance
        return {
            **counters,
            "futures": len(value.futures) if value else 0,
            "max_workers": value.executor._max_workers if value else 1,
        }

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def verify_prefixes(root):
    """Independently query calendar/status and stream every committed minute row."""
    import baostock as bs
    from backtest.loaders.baostock_loader import _baostock_socket_guard, _read_timeout

    jobs, chunks = snapshot(root)
    results = []

    def records(result):
        rows = []
        while result.error_code == "0" and result.next():
            rows.append(dict(zip(result.fields, result.get_row_data(), strict=True)))
        if result.error_code != "0":
            raise ValueError("Independent calendar/status query failed: " + result.error_code)
        return rows

    with _baostock_socket_guard(_read_timeout()) as acquired:
        if not acquired or bs.login().error_code != "0":
            raise RuntimeError("Independent verification login unavailable")
        try:
            for job in jobs:
                parts = [c for c in chunks if c["job"] == job["id"] and c["state"] == "complete"]
                assert parts and [c["idx"] for c in parts] == list(range(len(parts)))
                symbol = parts[0]["symbol"]
                start = parts[0]["start"]
                end = parts[-1]["end"]
                calendar = records(bs.query_trade_dates(start_date=start, end_date=end))
                assert len(calendar) == (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days + 1
                sessions = {r["calendar_date"] for r in calendar if r["is_trading_day"] == "1"}
                code, venue = symbol.split(".")
                daily = records(
                    bs.query_history_k_data_plus(
                        venue.lower() + "." + code,
                        "date,code,tradestatus",
                        start_date=start,
                        end_date=end,
                        frequency="d",
                        adjustflag="3",
                    )
                )
                assert len(daily) == len(sessions) and {r["date"] for r in daily} == sessions
                expected = {r["date"]: 48 for r in daily if r["tradestatus"] == "1"}
                counts = Counter()
                previous = None
                digest = hashlib.sha256()
                n = 0
                for chunk in parts:
                    p = root / "history" / job["id"] / f"{chunk['idx']}.jsonl.gz"
                    assert hashlib.sha256(p.read_bytes()).hexdigest() == chunk["digest"]
                    with gzip.open(p, "rt") as stream:
                        for line in stream:
                            row = json.loads(line)
                            stamp = row["time"]
                            point = datetime.fromisoformat(stamp)
                            assert row["symbol"] == symbol and (previous is None or stamp > previous)
                            allowed = {
                                point.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(minutes=i)
                                for h, m in ((9, 30), (13, 0))
                                for i in range(5, 121, 5)
                            }
                            assert point in allowed
                            previous = stamp
                            counts[stamp[:10]] += 1
                            n += 1
                            digest.update(line.encode())
                assert dict(counts) == expected and n == sum(c["rows"] for c in parts)
                results.append(
                    {
                        "symbol": symbol,
                        "chunks": len(parts),
                        "rows": n,
                        "sessions": len(counts),
                        "start": start,
                        "end": end,
                        "digest": digest.hexdigest(),
                        "scope": "committed_prefix_only",
                        "verified": True,
                    }
                )
        finally:
            bs.logout()
    return results


async def exercise(args):
    import httpx

    root = args.root
    start = time.monotonic()
    child = None
    streams = []
    paused = {}
    prefix = {}
    env = {k: v for k, v in os.environ.items() if not k.startswith("VIBE_GATEWAY_")}
    env.update(VIBE_GATEWAY_HISTORY_DIR=str(root / "history"), VIBE_GATEWAY_CACHE_DIR=str(root / "cache"))
    report = {"phases": [], "pids": [], "streams": [], "starts": 0, "full_download_complete": False}
    codes = json.loads(args.universe.read_text())["codes"]
    topics = ["crypto:BTC-USDT", "crypto:ETH-USDT"] + [f"bars:{s}:1D" for s in codes[:14]]
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{args.port}", timeout=15) as client:

        async def request(method, path, **kwargs):
            if method == "POST" and path.endswith("/resume"):
                report["starts"] += 1
            r = await client.request(method, path, **kwargs)
            r.raise_for_status()
            return r.json()

        async def stream(group, phase):
            stats = {"phase": phase, "events": 0, "ws": 0, "errors": []}
            report["streams"].append(stats)
            try:
                async with client.stream(
                    "GET", "/data/stream", params={"topics": ",".join(group)}, timeout=None
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            stats["events"] += 1
                            stats["ws"] += int('"websocket"' in line)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                stats["errors"].append(type(exc).__name__ + ": " + str(exc))

        async def stop_streams():
            for t in streams:
                t.cancel()
            await asyncio.gather(*streams, return_exceptions=True)
            streams.clear()

        def observe():
            jobs, chunks = snapshot(root)
            for c in chunks:
                key = (c["job"], c["idx"])
                if key in prefix:
                    assert c["state"] == "complete" and c["digest"] == prefix[key]
                if c["state"] == "complete":
                    assert (
                        hashlib.sha256((root / "history" / c["job"] / f"{c['idx']}.jsonl.gz").read_bytes()).hexdigest()
                        == c["digest"]
                    )
                    prefix[key] = c["digest"]
            values = {
                j["id"]: {
                    "id": j["id"],
                    "symbol": json.loads(j["spec"])["codes"][0],
                    "state": j["state"],
                    "auto_resume": j["auto_resume"],
                    "chunks": sum(c["state"] == "complete" for c in chunks if c["job"] == j["id"]),
                    "error": j["error"],
                }
                for j in jobs
            }
            for job, baseline in paused.items():
                assert values[job]["chunks"] == baseline["chunks"] and not values[job]["auto_resume"]
            return values, chunks

        try:
            for phase in range(4):
                phase_start = time.monotonic()
                hold = 12 if phase == 0 else len(prefix) + 15
                with (root / f"server-{phase}.log").open("w") as log:
                    child = subprocess.Popen(
                        [
                            sys.executable,
                            __file__,
                            "--server",
                            "--root",
                            str(root),
                            "--phase",
                            str(phase),
                            "--hold",
                            str(hold),
                            "--port",
                            str(args.port),
                        ],
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                report["pids"].append(child.pid)
                for _ in range(80):
                    if child.poll() is not None:
                        raise RuntimeError("Server startup failed")
                    try:
                        await request("GET", "/data/status")
                        break
                    except httpx.TransportError:
                        await asyncio.sleep(0.25)
                else:
                    raise RuntimeError("Startup timeout")
                streams = [asyncio.create_task(stream(topics[i : i + 8], phase)) for i in range(0, 16, 8)]
                scan = await request(
                    "POST",
                    "/data/scans",
                    json={"codes": codes, "start_date": "2026-11-02", "end_date": "2026-11-13", "interval": "1D"},
                )
                if phase == 0:
                    for symbol in SYMBOLS:
                        job = await request(
                            "POST",
                            "/data/history/jobs",
                            json={
                                "codes": [symbol],
                                "start_date": "2021-11-14",
                                "end_date": "2026-11-13",
                                "interval": "5m",
                            },
                        )
                        await request("POST", f"/data/history/jobs/{job['id']}/resume")
                while time.monotonic() - start < 360:
                    jobs, chunks = observe()
                    metrics = await request("GET", "/_probe/workers")
                    assert metrics["futures"] <= 4 and metrics["peak"] <= 1 and metrics["max_workers"] == 1
                    if (root / f"held-{phase}.json").exists():
                        break
                    await asyncio.sleep(0.3)
                else:
                    raise RuntimeError("Short-test time budget exhausted")
                assert len(jobs) == 10 and all(j["chunks"] > 0 for j in jobs.values())
                if phase == 0:
                    # Pause one actively acquired chunk, one executor queue item,
                    # and one disk-only waiting item after each has made progress.
                    for state in ("running", "queued", "waiting"):
                        chosen = next(j for j in jobs.values() if j["state"] == state and j["id"] not in paused)
                        await request("POST", f"/data/history/jobs/{chosen['id']}/cancel")
                        paused[chosen["id"]] = {**chosen, "pause_time": time.time(), "previous_state": state}
                    until = time.monotonic() + 15
                    while time.monotonic() < until:
                        jobs, chunks = observe()
                        if all(jobs[j]["state"] == "paused" for j in paused):
                            break
                        await asyncio.sleep(0.2)
                    else:
                        raise RuntimeError("Manual pauses did not settle")
                if phase:
                    previous = report["phases"][-1]["jobs"]
                    assert all(j["chunks"] > previous[jid]["chunks"] for jid, j in jobs.items() if jid not in paused)
                observed = {
                    "phase": phase,
                    "observed_at": time.time(),
                    "seconds": time.monotonic() - phase_start,
                    "jobs": jobs,
                    "workers": await request("GET", "/_probe/workers"),
                    "subscriptions": await request("GET", "/data/subscriptions"),
                    "scan": await request("GET", f"/data/scans/{scan['id']}"),
                    "gateway": await request("GET", "/data/status"),
                }
                assert len(observed["subscriptions"]["topics"]) == 16 and observed["scan"]["completed"] > 0
                report["phases"].append(observed)
                print(
                    json.dumps(
                        {
                            "phase": phase,
                            "seconds": observed["seconds"],
                            "completed_chunks": sum(j["chunks"] for j in jobs.values()),
                            "per_symbol": {j["symbol"]: j["chunks"] for j in jobs.values()},
                        }
                    ),
                    flush=True,
                )
                if phase == 3:
                    for job in jobs:
                        if job not in paused:
                            await request("POST", f"/data/history/jobs/{job}/cancel")
                    await request("POST", f"/data/scans/{scan['id']}/cancel")
                await stop_streams()
                if phase == 1:
                    child.kill()
                else:
                    child.terminate()
                await asyncio.to_thread(child.wait, timeout=15)
                observed["exit"] = child.returncode
                jobs, chunks = observe()
            calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
            assert not any(c.get("already_complete") for c in calls)
            for value in paused.values():
                assert not any(
                    c["event"] == "attempt" and c["symbol"] == value["symbol"] and c["time"] >= value["pause_time"]
                    for c in calls
                )
            assert report["starts"] == 10 and all(not s["errors"] for s in report["streams"])
            for phase in range(4):
                assert sum(s["ws"] for s in report["streams"] if s["phase"] == phase) > 0
            report.update(
                paused=list(paused.values()),
                final_jobs=jobs,
                planned_chunks=len(chunks),
                completed_chunks=sum(c["state"] == "complete" for c in chunks),
                rows=sum(c["rows"] for c in chunks),
                duplicate_committed_fetches=0,
                passed=True,
            )
        finally:
            await stop_streams()
            if child and child.poll() is None:
                child.terminate()
                await asyncio.to_thread(child.wait, timeout=15)
            report["elapsed_s"] = time.monotonic() - start
            (root / "report.json").write_text(json.dumps(report, indent=2))
    verified = await asyncio.to_thread(verify_prefixes, root)
    (root / "verification.json").write_text(json.dumps(verified, indent=2))
    traces = [json.loads(line) for line in (root / "scan-trace.jsonl").read_text().splitlines()]
    checkpoints = {phase["phase"]: phase["observed_at"] for phase in report["phases"]}
    batches = [r for r in traces if r["event"] == "bars" and r["time"] <= checkpoints[r["phase"]]]
    missing = [r for r in batches if set(r["codes"]) != set(r["returned"]) or not r["ok"]]
    report["scan_validation"] = {
        "completed_requests": len(batches),
        "max_request_seconds": max((r["elapsed"] for r in batches), default=0),
        "missing_batches": missing,
        "zero_retries": all(p["scan"]["retries"] == 0 and p["scan"]["failed"] == 0 for p in report["phases"]),
        "scope": "completed requests before phase checkpoints; in-flight work may be interrupted by restart",
    }
    report["passed"] = report["passed"] and not missing and report["scan_validation"]["zero_retries"]
    report.update(prefixes_verified=True, total_seconds=time.monotonic() - start)
    (root / "report.json").write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("passed", "prefixes_verified", "completed_chunks", "planned_chunks", "rows", "total_seconds")
            }
        ),
        flush=True,
    )

    assert report["passed"], "Mixed scan had missing rows, retries or failures; see report and scan-trace"

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--universe", type=Path)
    p.add_argument("--server", action="store_true")
    p.add_argument("--phase", type=int, default=0)
    p.add_argument("--hold", type=int, default=0)
    p.add_argument("--port", type=int, default=8926)
    args = p.parse_args()
    if args.server:
        server(args)
        return
    if not args.universe or args.root.exists() or any((x / ".git").exists() for x in (args.root, *args.root.parents)):
        p.error("Supply real universe JSON and a fresh root outside checkouts")
    args.root.mkdir(parents=True)
    asyncio.run(exercise(args))


if __name__ == "__main__":
    main()
