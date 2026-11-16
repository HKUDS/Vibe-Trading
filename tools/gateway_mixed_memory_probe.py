"""Short real mixed load with separately observed plain/instrumented server memory.

The plain child runs the gateway module directly: no tracing monkeypatch, probe
endpoint or controller import executes in it. All sampling stays in this process.
"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from gateway_full_scan_probe import memory_tree
from gateway_ten_job_restart_probe import SYMBOLS, verify_prefixes


async def exercise(args):
    """Run ten histories, sixteen topics and a scan under unchanged defaults."""
    import httpx

    args.root.mkdir(parents=True, exist_ok=False)
    universe = args.universe.read_bytes()
    codes = json.loads(universe)["codes"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("VIBE_GATEWAY_")}
    env.update(
        VIBE_GATEWAY_HISTORY_DIR=str(args.root / "history"),
        VIBE_GATEWAY_CACHE_DIR=str(args.root / "cache"),
        VIBE_TRADING_HOME=str(args.root / "runtime"),
        VIBE_TRADING_DATA_CACHE="0",
        VIBE_GATEWAY_PORT=str(args.port),
    )
    command = (
        [sys.executable, "-m", "src.data_gateway.dev_server"]
        if args.mode == "plain"
        else [
            sys.executable,
            "tools/gateway_full_scan_probe.py",
            "--server",
            "--root",
            str(args.root),
            "--port",
            str(args.port),
        ]
    )
    report = {
        "mode": args.mode,
        "universe_sha256": hashlib.sha256(universe).hexdigest(),
        "streams": [],
        "errors": [],
        "limits_changed": False,
        "controller_pid": os.getpid(),
        "command": command,
    }
    start = time.monotonic()
    feeds, scan = [], None
    stopped = False
    with (args.root / "server.log").open("w") as log:
        child = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    report["pid"] = child.pid

    def save():
        report["elapsed_seconds"] = time.monotonic() - start
        temporary = args.root / "report.tmp"
        temporary.write_text(json.dumps(report, indent=2))
        temporary.replace(args.root / "report.json")

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{args.port}", timeout=15) as client:

        async def request(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        async def feed(topics):
            stats = {"events": 0, "websocket": 0, "source_errors": 0, "errors": []}
            report["streams"].append(stats)
            try:
                async with client.stream(
                    "GET", "/data/stream", params={"topics": ",".join(topics)}, timeout=None
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            value = json.loads(line[5:])
                            stats["events"] += 1
                            stats["websocket"] += int('"websocket"' in line)
                            stats["source_errors"] += int(
                                value.get("event") == "source_error" or value.get("payload", {}).get("ok") is False
                            )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                stats["errors"].append(repr(exc))

        async def sample(phase):
            gateway = await request("GET", "/data/status")
            jobs = await request("GET", "/data/history/jobs")
            progress = await request("GET", f"/data/scans/{scan['id']}") if phase == "active" else None
            value = {
                "elapsed_seconds": time.monotonic() - start,
                "phase": phase,
                "server": memory_tree(child.pid),
                "controller": memory_tree(os.getpid())["processes"][0],
                "gateway": gateway,
                "jobs": jobs,
                "scan": progress,
                "streams": [dict(s) for s in report["streams"]],
            }
            assert gateway["limits"] == {
                "memory_bytes": 8 * 2**20,
                "disk_bytes": 64 * 2**20,
                "workers": 4,
                "pending": 16,
            }
            assert gateway["cache"]["memory_bytes"] <= 8 * 2**20 and gateway["cache"]["disk_bytes"] <= 64 * 2**20
            with (args.root / "samples.jsonl").open("a") as stream:
                stream.write(json.dumps(value) + "\n")
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
                await request("POST", f"/data/scans/{scan['id']}/cancel")
            for job in await request("GET", "/data/history/jobs"):
                if job["state"] != "complete":
                    await request("POST", f"/data/history/jobs/{job['id']}/cancel")

        try:
            for _ in range(100):
                if child.poll() is not None:
                    raise RuntimeError("Server exited at startup")
                try:
                    await request("GET", "/data/status")
                    break
                except httpx.TransportError:
                    await asyncio.sleep(0.25)
            else:
                raise RuntimeError("Startup deadline")
            await sample("baseline")
            topics = ["crypto:BTC-USDT", "crypto:ETH-USDT"] + [f"bars:{c}:1D" for c in codes[:14]]
            feeds = [asyncio.create_task(feed(topics[i : i + 8])) for i in range(0, 16, 8)]
            for code in SYMBOLS:
                job = await request(
                    "POST",
                    "/data/history/jobs",
                    json={"codes": [code], "start_date": "2021-11-14", "end_date": "2026-11-13", "interval": "5m"},
                )
                await request("POST", f"/data/history/jobs/{job['id']}/resume")
            scan = await request(
                "POST",
                "/data/scans",
                json={"codes": codes, "start_date": "2026-11-02", "end_date": "2026-11-13", "interval": "1D"},
            )
            active_start = time.monotonic()
            while time.monotonic() - active_start < args.seconds:
                await sample("active")
                await asyncio.sleep(2)
            report["scan_final"] = await request("GET", f"/data/scans/{scan['id']}")
            await stop_load()
            idle = time.monotonic()
            while time.monotonic() - idle < args.idle:
                await sample("idle")
                await asyncio.sleep(2)
            report["storage"] = await request("GET", "/data/history/storage")
            assert report["storage"]["quota_bytes"] == 256 * 2**20
        except Exception as exc:
            report["errors"].append(repr(exc))
            raise
        finally:
            try:
                if child.poll() is None:
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
    verified = await asyncio.to_thread(verify_prefixes, args.root)
    (args.root / "verification.json").write_text(json.dumps(verified, indent=2))
    report.update(phase="complete", prefixes_verified=all(v["verified"] for v in verified))
    save()
    print(json.dumps({k: report[k] for k in ("mode", "scan_final", "streams", "errors", "prefixes_verified")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--mode", choices=["plain", "instrumented"], required=True)
    parser.add_argument("--seconds", type=float, default=240)
    parser.add_argument("--idle", type=float, default=180)
    parser.add_argument("--port", type=int, default=8926)
    asyncio.run(exercise(parser.parse_args()))
