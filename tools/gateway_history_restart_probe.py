"""Real-source app restart probe: graceful close and process kill, no client resume.

A test-only hold interrupts the second symbol after a real committed prefix.
Restart uses the production gateway app lifespan, with no history API calls until
SQLite shows completion. The client never resumes a job after process restart.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time


def server(args):
    import uvicorn
    from src.data_gateway import history_router

    original = history_router.fetch_chunk

    def fetch(symbol, *rest):
        with (args.root / "calls.jsonl").open("a") as stream:
            stream.write(json.dumps({"pid": os.getpid(), "symbol": symbol, "phase": args.phase}) + "\n")
        if args.phase == "before" and symbol == "MSFT.US":
            context = history_router.history_context.get() or {}
            while not context.get("stop_requested", lambda: False)():
                time.sleep(0.1)
            raise history_router.HistoryPaused()
        return original(symbol, *rest)

    history_router.fetch_chunk = fetch
    from src.data_gateway.dev_server import app

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def run_case(args, mode):
    import httpx

    root = args.root / mode
    root.mkdir()
    history = root / "history"
    env = {k: v for k, v in os.environ.items() if not k.startswith("VIBE_GATEWAY_")}
    env.update(VIBE_GATEWAY_HISTORY_DIR=str(history), VIBE_GATEWAY_CACHE_DIR=str(root / "cache"))
    report = {
        "mode": mode,
        "resume_posts": 0,
        "pids": [],
        "method": "production app lifespan; no history HTTP reads after restart until catalog is complete",
    }
    started = time.monotonic()
    child = None
    with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=15) as client:

        def request(method, path, **kwargs):
            if method == "POST" and path.endswith("/resume"):
                report["resume_posts"] += 1
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        def boot(phase):
            with (root / f"{phase}.log").open("w") as log:
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        __file__,
                        "--server",
                        "--phase",
                        phase,
                        "--root",
                        str(root),
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
                    raise RuntimeError("Server exited at startup: " + (root / f"{phase}.log").read_text()[-2000:])
                try:
                    request("GET", "/data/status")  # Does not initialize history storage.
                    return proc
                except httpx.TransportError:
                    time.sleep(0.25)
            proc.terminate()
            proc.wait(timeout=15)
            raise RuntimeError("Server startup failed")

        def create(codes):
            return request(
                "POST",
                "/data/history/jobs",
                json={"codes": codes, "start_date": "2021-11-14", "end_date": "2026-11-13", "interval": "1M"},
            )["id"]

        try:
            child = boot("before")
            active = create(["AAPL.US", "MSFT.US"])
            request("POST", f"/data/history/jobs/{active}/resume")
            until = time.monotonic() + 45
            while time.monotonic() < until:
                state = request("GET", f"/data/history/jobs/{active}")
                if state["completed_chunks"] == 1 and state["reserved"] > 0:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("Real prefix did not commit")
            prefix = hashlib.sha256((history / active / "0.jsonl.gz").read_bytes()).hexdigest()
            queued, paused, untouched = create(["GOOGL.US"]), create(["TSLA.US"]), create(["AMZN.US"])
            request("POST", f"/data/history/jobs/{queued}/resume")
            request("POST", f"/data/history/jobs/{paused}/resume")
            request("POST", f"/data/history/jobs/{paused}/cancel")
            report["before"] = {
                "active": state,
                "queued": request("GET", f"/data/history/jobs/{queued}"),
                "paused": request("GET", f"/data/history/jobs/{paused}"),
            }
            if mode == "kill":
                child.kill()
            else:
                child.terminate()
            child.wait(timeout=15)
            report["first_exit"] = child.returncode
            with sqlite3.connect(history / "catalog.sqlite") as db:
                db.row_factory = sqlite3.Row
                stopped = {
                    row["id"]: dict(row)
                    for row in db.execute("SELECT id,state,auto_resume,cancel,reserved,retry_at,owner FROM jobs")
                }
            report["after_stop"] = stopped
            if mode == "graceful":
                for job in (active, queued):
                    assert stopped[job]["state"] == "failed" and stopped[job]["retry_at"] > 0
                    assert stopped[job]["reserved"] == 0 and stopped[job]["owner"] is None
                assert stopped[paused]["state"] == "paused" and not stopped[paused]["auto_resume"]
            else:
                assert stopped[active]["state"] == "running" and stopped[active]["reserved"] > 0
                assert stopped[queued]["state"] == "queued"
            restarted = time.monotonic()
            child = boot("after")
            until = time.monotonic() + 45
            while time.monotonic() < until:
                with sqlite3.connect(history / "catalog.sqlite") as db:
                    states = dict(db.execute("SELECT id,state FROM jobs"))
                if states.get(active) == states.get(queued) == "complete":
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("Startup recovery did not finish: " + repr(states))
            report["restart_to_complete_s"] = time.monotonic() - restarted
            assert states[paused] == states[untouched] == "paused"
            assert hashlib.sha256((history / active / "0.jsonl.gz").read_bytes()).hexdigest() == prefix
            report["after"] = request("GET", "/data/history/jobs")
            rows = 0
            for job in (active, queued):
                page = request("GET", f"/data/history/jobs/{job}/rows", params={"limit": 1000})
                assert page["coverage_verified"] and page["next_offset"] is None
                rows += len(page["rows"])
            assert rows == 183
            report.update(
                rows=rows,
                prefix_unchanged=True,
                gateway=request("GET", "/data/status"),
                storage=request("GET", "/data/history/storage"),
            )
            report["calls"] = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
            assert sum(c["symbol"] == "AAPL.US" for c in report["calls"]) == 1
            assert not any(c["symbol"] in {"TSLA.US", "AMZN.US"} for c in report["calls"])
            assert report["resume_posts"] == 3  # Only initial user starts, never restart recovery.
            assert report["storage"]["reserved_bytes"] == 0
            report["complete"] = True
        finally:
            if child and child.poll() is None:
                child.terminate()
                child.wait(timeout=15)
            report["elapsed_s"] = time.monotonic() - started
            (root / "report.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8924)
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--phase", choices=["before", "after"])
    args = parser.parse_args()
    if args.server:
        server(args)
        return
    if args.root.exists() or any((p / ".git").exists() for p in (args.root, *args.root.parents)):
        parser.error("Use a fresh directory outside every checkout")
    args.root.mkdir(parents=True)
    reports = [run_case(args, mode) for mode in ("graceful", "kill")]
    print(
        json.dumps(
            [
                {k: r[k] for k in ("mode", "complete", "rows", "restart_to_complete_s", "elapsed_s", "pids")}
                for r in reports
            ]
        )
    )


if __name__ == "__main__":
    main()
