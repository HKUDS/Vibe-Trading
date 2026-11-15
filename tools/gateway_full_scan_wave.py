"""Explicitly add one ten-job history wave to an active full-scan experiment.

No background replenisher: invoke once after the prior wave has completed.
Retires oldest completed test datasets only when the existing 32-job catalog
cannot fit the next wave. Records their terminal metadata before deletion.
"""

import argparse
import asyncio
import json
from pathlib import Path
import time

from gateway_ten_job_restart_probe import SYMBOLS


async def add_wave(args):
    """Add real acquisition load without modifying any production limits.

    Args:
        args: CLI paths, loopback port, and requested historical range.
    """
    import httpx

    document = json.loads((args.root / "report.json").read_text())
    if document["phase"] != "active" or document.get("scan_final"):
        raise RuntimeError("Full scan is no longer active")
    event = {"started_at": time.time(), "start_date": args.start_date, "end_date": args.end_date,
             "completed_before": [], "retired": [], "created": []}
    events = args.root / "history-waves.jsonl"

    def record(kind, **value):
        with events.open("a") as stream:
            stream.write(json.dumps({"time": time.time(), "event": kind, **value}) + "\n")

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{args.port}", timeout=15) as client:
        async def request(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        scan = await request("GET", f"/data/scans/{document['scan_id']}")
        if scan["state"] != "running":
            raise RuntimeError("Scan has reached terminal state")
        jobs = await request("GET", "/data/history/jobs")
        if any(j["state"] != "complete" for j in jobs):
            raise RuntimeError("Prior history wave is still unfinished; do not exceed ten active jobs")
        event["completed_before"] = jobs
        record("wave_start", **event)
        # API returns newest first. Never modify quota or delete active work.
        for job in list(reversed(jobs))[:max(0, len(jobs) + len(SYMBOLS) - 32)]:
            record("retire_completed", job=job)
            await request("DELETE", f"/data/history/jobs/{job['id']}")
            event["retired"].append(job["id"])
        for symbol in SYMBOLS:
            job = await request("POST", "/data/history/jobs", json={"codes": [symbol], "start_date": args.start_date,
                                "end_date": args.end_date, "interval": "5m"})
            record("created", symbol=symbol, job=job)
            await request("POST", f"/data/history/jobs/{job['id']}/resume")
            event["created"].append(job["id"])
        record("wave_started", **event)
        print(json.dumps({"created": len(event["created"]), "retired": len(event["retired"]),
                          "scan_completed": scan["completed"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8926)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    asyncio.run(add_wave(parser.parse_args()))
