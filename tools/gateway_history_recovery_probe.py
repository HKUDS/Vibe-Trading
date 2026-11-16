"""Short real-source automatic history recovery probe; no client resume loop.

Only the first start uses POST /resume. A test-only transport failure blocks
MSFT while AAPL's real monthly chunk commits. Removing the fault does not call
any scheduler or recovery method. Prices are never synthesized or saved in the
report; the production service must resume and finish the persisted dataset.
"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def server(args):
    import gateway_soak

    original = gateway_soak.instrument_history

    def instrument(*values):
        store = original(*values)
        fetch = store.fetcher

        def controlled(symbol, *rest):
            with args.calls.open("a") as stream:
                stream.write(
                    json.dumps(
                        {"symbol": symbol, "time": time.time(), "blocked": symbol == "MSFT.US" and args.fault.exists()}
                    )
                    + "\n"
                )
            if symbol == "MSFT.US" and args.fault.exists():
                raise ConnectionError("probe transport unavailable")
            return fetch(symbol, *rest)

        store.fetcher = controlled
        return store

    gateway_soak.instrument_history = instrument
    gateway_soak.serve(args.port)


async def exercise(args):
    import httpx

    started = time.monotonic()
    base = f"http://127.0.0.1:{args.port}"
    report = {
        "method": "Real public data, targeted transport fault, exactly one initial resume POST; production cleaner alone dispatches retries",
        "resume_posts": 0,
        "states": [],
        "events": 0,
    }
    streams = []
    scan = None
    async with httpx.AsyncClient(timeout=20) as client:

        async def request(method, path, **kwargs):
            if method == "POST" and path.endswith("/resume"):
                report["resume_posts"] += 1
            response = await client.request(method, base + path, **kwargs)
            response.raise_for_status()
            return response.json()

        for _ in range(60):
            try:
                await request("GET", "/data/status")
                break
            except httpx.TransportError:
                await asyncio.sleep(0.5)
        else:
            raise RuntimeError("Probe server failed to start")

        universe = json.loads(args.universe.read_text())["codes"]
        topics = ["crypto:BTC-USDT", "crypto:ETH-USDT"] + [f"bars:{code}:1D" for code in universe[:62]]

        async def stream(group):
            async with client.stream(
                "GET", base + "/data/stream", params={"topics": ",".join(group)}, timeout=None
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        report["events"] += 1

        streams = [asyncio.create_task(stream(topics[i : i + 8])) for i in range(0, 64, 8)]
        try:
            scan = await request(
                "POST",
                "/data/scans",
                json={"codes": universe, "start_date": "2026-11-02", "end_date": "2026-11-13", "interval": "1D"},
            )
            spec = {
                "codes": ["AAPL.US", "MSFT.US"],
                "start_date": "2021-11-14",
                "end_date": "2026-11-13",
                "interval": "1M",
            }
            job = await request("POST", "/data/history/jobs", json=spec)
            report["job"] = job["id"]
            await request("POST", f"/data/history/jobs/{job['id']}/resume")
            prefix = None
            until = time.monotonic() + 90
            while time.monotonic() < until:
                state = await request("GET", f"/data/history/jobs/{job['id']}")
                report["states"].append(
                    {
                        k: state.get(k)
                        for k in ("state", "retry_at", "retry_count", "completed_chunks", "rows", "reserved", "error")
                    }
                )
                if state.get("retry_at") and args.fault.exists():
                    assert state["completed_chunks"] == 1 and state["reserved"] == 0
                    prefix = hashlib.sha256((args.history / job["id"] / "0.jsonl.gz").read_bytes()).hexdigest()
                    report["fault_removed_s"] = time.monotonic() - started
                    args.fault.unlink()  # Network restoration only; no recovery API.
                if state["state"] == "complete":
                    assert (
                        prefix
                        and prefix == hashlib.sha256((args.history / job["id"] / "0.jsonl.gz").read_bytes()).hexdigest()
                    )
                    page = await request("GET", f"/data/history/jobs/{job['id']}/rows", params={"limit": 1000})
                    assert page["coverage_verified"] and len(page["rows"]) == 122 and page["next_offset"] is None
                    report.update(
                        complete=True,
                        rows=state["rows"],
                        prefix_unchanged=True,
                        seconds=time.monotonic() - started,
                        provenance=page["provenance"],
                    )
                    break
                await asyncio.sleep(0.5)
            else:
                raise RuntimeError("Automatic recovery did not complete within 90 seconds")
            report["subscriptions"] = await request("GET", "/data/subscriptions")
            report["scan"] = await request("GET", f"/data/scans/{scan['id']}")
            report["metrics_active"] = await request("GET", "/_soak/metrics")
        finally:
            for task in streams:
                task.cancel()
            outcomes = await asyncio.gather(*streams, return_exceptions=True)
            report["stream_errors"] = [str(value) for value in outcomes if isinstance(value, Exception)]
            if scan:
                await request("POST", f"/data/scans/{scan['id']}/cancel")
            for _ in range(20):
                metrics = await request("GET", "/_soak/metrics")
                if metrics["gateway"]["active_requests"] == 0 and not metrics["sockets"]:
                    break
                await asyncio.sleep(1)
            report["metrics_idle"] = metrics
            report["calls"] = [json.loads(line) for line in args.calls.read_text().splitlines()]
            report["elapsed_s"] = time.monotonic() - started
            args.output.write_text(json.dumps(report, indent=2))
    assert report["resume_posts"] == 1 and report.get("complete")
    assert sum(row["symbol"] == "AAPL.US" for row in report["calls"]) == 1
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "complete",
                    "resume_posts",
                    "rows",
                    "prefix_unchanged",
                    "seconds",
                    "elapsed_s",
                    "stream_errors",
                )
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--port", type=int, default=8923)
    for name in ("history", "fault", "calls", "output", "universe"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.server:
        server(args)
        return
    if args.history.exists() or args.output.exists() or args.calls.exists():
        parser.error("Use fresh history and report paths outside the checkout")
    args.fault.write_text("transport offline")
    with tempfile.TemporaryDirectory(prefix="gateway-recovery-cache-") as cache:
        env = {k: v for k, v in os.environ.items() if not k.startswith("VIBE_GATEWAY_")}
        env.update(
            VIBE_GATEWAY_CACHE_DIR=cache,
            VIBE_GATEWAY_HISTORY_DIR=str(args.history),
            VIBE_GATEWAY_SOAK_HISTORY="1",
            VIBE_GATEWAY_STREAM_TOPICS="64",
        )
        with args.output.with_suffix(".server.log").open("w") as log:
            child = subprocess.Popen(
                [sys.executable, __file__, *sys.argv[1:], "--server"], env=env, stdout=log, stderr=subprocess.STDOUT
            )
            try:
                asyncio.run(exercise(args))
            finally:
                child.terminate()
                child.wait(timeout=45)
                args.fault.unlink(missing_ok=True)
                args.output.with_suffix(".exit.json").write_text(
                    json.dumps({"server_pid": child.pid, "returncode": child.returncode})
                )


if __name__ == "__main__":
    main()
