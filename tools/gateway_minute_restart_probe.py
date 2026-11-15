"""Five-year 5m history, four process restarts, concurrent SSE and scan load.

Only committed chunks must never be fetched again. A deliberately interrupted,
uncommitted chunk is allowed to be reacquired. Prices always come from real
sources; a test-only post-fetch hold makes the crash boundary deterministic.
"""

import argparse
import asyncio
from collections import Counter
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time


def snapshot(root):
    with closing(sqlite3.connect(root / "history/catalog.sqlite")) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM jobs")], [
            dict(row) for row in db.execute("SELECT * FROM chunks ORDER BY job,idx")
        ]


def audit_report(root, report):
    """Replay invariants against captured calls and final persisted chunks."""
    _, chunks = snapshot(root)
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    indices = {(c["symbol"], c["start"], c["end"]): c["idx"] for c in chunks}
    for call in calls:
        previous = 0 if call["phase"] == 0 else report["phases"][call["phase"] - 1]["completed_chunks"]
        assert indices[call["symbol"], call["start"], call["end"]] >= previous
    assert all(not stream["errors"] for stream in report["streams"])
    for phase in report["phases"]:
        assert sum(s["websocket_updates"] for s in report["streams"] if s["phase"] == phase["phase"]) > 0
        assert phase["scan"]["completed"] > 0 and phase["scan"]["failed"] == 0
        assert phase["gateway"]["limits"] == {
            "memory_bytes": 8 * 1024**2,
            "disk_bytes": 64 * 1024**2,
            "workers": 4,
            "pending": 16,
        }
    assert report["paused"]["auto_resume"] == 0 and report["paused"]["rows"] == 0
    assert report["storage"]["quota_bytes"] == 256 * 1024**2


def server(args):
    import uvicorn
    from src.data_gateway import history_router

    original = history_router.fetch_chunk

    def record(value):
        with (args.root / "calls.jsonl").open("a") as stream:
            stream.write(json.dumps({"phase": args.phase, **value}) + "\n")

    def fetch(symbol, start, end, interval):
        identity = {"symbol": symbol, "start": start, "end": end, "interval": interval}
        record({**identity, "event": "attempt"})
        rows, meta = original(symbol, start, end, interval)
        record({**identity, "event": "acquired", "rows": len(rows)})
        if symbol == "601398.SH" and args.hold >= 0:
            _, chunks = snapshot(args.root)
            count = sum(c["state"] == "complete" and c["symbol"] == symbol for c in chunks)
            if count >= args.hold:
                (args.root / f"held-{args.phase}.json").write_text(json.dumps(identity))
                context = history_router.history_context.get() or {}
                while not context.get("stop_requested", lambda: False)():
                    time.sleep(0.05)
                raise history_router.HistoryPaused()
        return rows, meta

    history_router.fetch_chunk = fetch
    from src.data_gateway.dev_server import app

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


async def exercise(args):
    import httpx

    root = args.root
    env = {k: v for k, v in os.environ.items() if not k.startswith("VIBE_GATEWAY_")}
    env.update(VIBE_GATEWAY_HISTORY_DIR=str(root / "history"), VIBE_GATEWAY_CACHE_DIR=str(root / "cache"))
    report = {"phases": [], "resume_posts": 0, "streams": [], "pids": [], "limits_changed": False}
    started = time.monotonic()
    child = None
    streams = []
    committed = {}
    main_job = paused_job = None
    codes = json.loads(args.universe.read_text())["codes"]
    topics = ["crypto:BTC-USDT", "crypto:ETH-USDT"] + [f"bars:{c}:1D" for c in codes[:14]]
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{args.port}", timeout=15) as client:

        async def request(method, path, **kwargs):
            if method == "POST" and path.endswith("/resume"):
                report["resume_posts"] += 1
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        async def feed(group, phase):
            record = {"phase": phase, "events": 0, "websocket_updates": 0, "errors": []}
            report["streams"].append(record)
            try:
                async with client.stream(
                    "GET", "/data/stream", params={"topics": ",".join(group)}, timeout=None
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            record["events"] += 1
                            payload = json.loads(line[5:])
                            # Stream updates may wrap the snapshot in data.
                            if '"websocket"' in json.dumps(payload) or '"ws"' in json.dumps(payload):
                                record["websocket_updates"] += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                record["errors"].append(type(exc).__name__ + ": " + str(exc))

        async def boot(phase, hold):
            with (root / f"server-{phase}.log").open("w") as log:
                proc = subprocess.Popen(
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
            report["pids"].append(proc.pid)
            for _ in range(80):
                if proc.poll() is not None:
                    raise RuntimeError(f"Server {phase} exited at startup")
                try:
                    await request("GET", "/data/status")
                    return proc
                except httpx.TransportError:
                    await asyncio.sleep(0.25)
            proc.terminate()
            await asyncio.to_thread(proc.wait, timeout=15)
            raise RuntimeError("Startup timed out")

        async def stop_streams():
            for stream in streams:
                stream.cancel()
            await asyncio.gather(*streams, return_exceptions=True)
            streams.clear()

        def verify_prefix(chunks):
            for chunk in chunks:
                key = (chunk["job"], chunk["idx"])
                if key in committed:
                    assert chunk["state"] == "complete" and chunk["digest"] == committed[key]
                    path = root / "history" / chunk["job"] / f"{chunk['idx']}.jsonl.gz"
                    assert hashlib.sha256(path.read_bytes()).hexdigest() == committed[key]
                elif chunk["state"] == "complete":
                    committed[key] = chunk["digest"]

        try:
            for phase, hold in enumerate((2, 7, 15, 30, -1)):
                phase_start = time.monotonic()
                child = await boot(phase, hold)
                streams = [asyncio.create_task(feed(topics[i : i + 8], phase)) for i in range(0, 16, 8)]
                scan = await request(
                    "POST",
                    "/data/scans",
                    json={"codes": codes, "start_date": "2026-11-02", "end_date": "2026-11-13", "interval": "1D"},
                )
                if phase == 0:
                    spec = {"start_date": "2021-11-14", "end_date": "2026-11-13", "interval": "5m"}
                    main_job = (await request("POST", "/data/history/jobs", json={**spec, "codes": ["601398.SH"]}))[
                        "id"
                    ]
                    paused_job = (await request("POST", "/data/history/jobs", json={**spec, "codes": ["600519.SH"]}))[
                        "id"
                    ]
                    await request("POST", f"/data/history/jobs/{main_job}/resume")
                    await request("POST", f"/data/history/jobs/{paused_job}/resume")
                    await request("POST", f"/data/history/jobs/{paused_job}/cancel")
                # After restart, only SQLite observes progress. No history HTTP
                # request or manual resume can initialize/recover the service.
                while time.monotonic() - started < 360:
                    jobs, chunks = snapshot(root)
                    states = {j["id"]: j for j in jobs}
                    assert states[paused_job]["auto_resume"] == 0 and states[paused_job]["cancel"] == 1
                    assert not any(c["rows"] for c in chunks if c["job"] == paused_job)
                    if (hold >= 0 and (root / f"held-{phase}.json").exists()) or states[main_job][
                        "state"
                    ] == "complete":
                        break
                    await asyncio.sleep(0.25)
                else:
                    raise RuntimeError("Short-test time budget exhausted")
                verify_prefix(chunks)
                main = states[main_job]
                observed = {
                    "phase": phase,
                    "seconds": time.monotonic() - phase_start,
                    "completed_chunks": sum(c["state"] == "complete" and c["job"] == main_job for c in chunks),
                    "state": main["state"],
                    "subscriptions": await request("GET", "/data/subscriptions"),
                    "scan": await request("GET", f"/data/scans/{scan['id']}"),
                    "gateway": await request("GET", "/data/status"),
                }
                assert len(observed["subscriptions"]["topics"]) == 16
                report["phases"].append(observed)
                print(
                    json.dumps({k: observed[k] for k in ("phase", "seconds", "completed_chunks", "state")}), flush=True
                )
                if hold >= 0:
                    await stop_streams()
                    if phase % 2:
                        child.kill()
                    else:
                        child.terminate()
                    await asyncio.to_thread(child.wait, timeout=15)
                    observed["exit"] = child.returncode
                else:
                    assert main["state"] == "complete"
                    # Read every actual HTTP row page, retaining only a digest.
                    digest, offset, pages = hashlib.sha256(), 0, 0
                    while True:
                        page = await request(
                            "GET", f"/data/history/jobs/{main_job}/rows", params={"offset": offset, "limit": 1000}
                        )
                        assert page["coverage_verified"] and not page["sampled"]
                        for row in page["rows"]:
                            digest.update((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode())
                        offset += len(page["rows"])
                        pages += 1
                        if page["next_offset"] is None:
                            break
                        assert page["next_offset"] == offset
                    report.update(job=main_job, rows=offset, http_pages=pages, http_digest=digest.hexdigest())
                    await request("POST", f"/data/scans/{scan['id']}/cancel")
                    await stop_streams()
                    report["paused"] = await request("GET", f"/data/history/jobs/{paused_job}")
                    report["storage"] = await request("GET", "/data/history/storage")
                    assert report["paused"]["state"] == "paused" and report["storage"]["reserved_bytes"] == 0
            calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
            attempts = Counter((c["symbol"], c["start"], c["end"]) for c in calls if c["event"] == "attempt")
            held = {
                tuple(json.loads(p.read_text())[k] for k in ("symbol", "start", "end"))
                for p in root.glob("held-*.json")
            }
            assert not any(c["symbol"] == "600519.SH" for c in calls)
            assert all(n == 1 or key in held for key, n in attempts.items())
            assert len(held) == 4 and report["resume_posts"] == 2
            report.update(
                unique_chunks=len(attempts),
                total_attempts=sum(attempts.values()),
                interrupted_uncommitted_chunks=len(held),
                completed_prefixes_unchanged=True,
            )
        finally:
            await stop_streams()
            if child and child.poll() is None:
                child.terminate()
                await asyncio.to_thread(child.wait, timeout=15)
            report["elapsed_s"] = time.monotonic() - started
            (root / "report.json").write_text(json.dumps(report, indent=2))
    # Independent full-range daily/calendar verification after process shutdown.
    from src.data_gateway.history_store import HistoryStore
    from gateway_history_validate import verify

    store = HistoryStore(root / "history")
    try:
        verification = await asyncio.to_thread(verify, store, main_job)
        assert verification["canonical_sha256"] == report["http_digest"]
        (root / "verification.json").write_text(json.dumps(verification, indent=2))
        audit_report(root, report)
        report.update(
            verified=True, verification_rows=verification["total_rows"], total_seconds=time.monotonic() - started
        )
        (root / "report.json").write_text(json.dumps(report, indent=2))
    finally:
        store.close()
    print(
        json.dumps({k: report[k] for k in ("verified", "rows", "unique_chunks", "total_attempts", "total_seconds")}),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--universe", type=Path)
    parser.add_argument("--port", type=int, default=8925)
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--phase", type=int, default=0)
    parser.add_argument("--hold", type=int, default=-1)
    args = parser.parse_args()
    if args.server:
        server(args)
        return
    if not args.universe:
        parser.error("Provide the real universe JSON with --universe")
    if args.root.exists() or any((p / ".git").exists() for p in (args.root, *args.root.parents)):
        parser.error("Use a fresh directory outside every checkout")
    args.root.mkdir(parents=True)
    asyncio.run(exercise(args))


if __name__ == "__main__":
    main()
