"""Observe fresh crypto events and recovery; cached replays never prove recovery."""

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
import time

import httpx
from gateway_soak_history import Timings


async def run(args):
    timings = Timings()
    counts = Counter()
    recoveries = defaultdict(dict)
    state = {}
    finished = asyncio.Event()
    error = None

    def save():
        args.output.write_text(
            json.dumps(
                {
                    "phase": state.get("phase"),
                    "counts": dict(counts),
                    "timings": timings.summary(),
                    "recoveries": dict(recoveries),
                    "error": error,
                },
                indent=2,
            )
        )

    async def monitor():
        while not finished.is_set():
            state.update(json.loads(args.soak.read_text()))
            save()
            if state["phase"] in {"idle", "complete"}:
                finished.set()
                return
            await asyncio.sleep(2)

    async def stream():
        nonlocal error
        async with httpx.AsyncClient(timeout=None) as client:
            try:
                async with client.stream(
                    "GET", args.url + "/data/stream", params={"topics": "crypto:BTC-USDT,crypto:ETH-USDT"}
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        value = json.loads(line[6:])
                        counts[value["event"]] += 1
                        if value["event"] != "snapshot":
                            continue
                        payload = value["payload"]
                        metadata = payload.get("gateway", {})
                        transport = metadata.get("transport", "unknown")
                        counts[transport] += 1
                        received = time.time()
                        fetched = datetime.fromisoformat(metadata["fetched_at"]).timestamp()
                        timings.add(transport + ":gateway_to_client", max(0, received - fetched))
                        source = payload.get("data", {}).get("source_time_ms")
                        if source:
                            timings.add(transport + ":source_age", max(0, received - source / 1000))
                        if not state.get("transitions"):
                            continue
                        transition = state["transitions"][-1]
                        epoch = datetime.fromisoformat(state["started_utc"]).timestamp() + transition["elapsed_s"]
                        # Require a newly fetched event after the transition.
                        if fetched < epoch:
                            counts["pre_transition_snapshot"] += 1
                            continue
                        key = str(transition["elapsed_s"])
                        record = recoveries.setdefault(
                            key, {"mode": transition["mode"], "cycle": transition["cycle"], "events": {}}
                        )
                        event_key = value["topic"] + ":" + transport
                        record["events"].setdefault(event_key, round(received - epoch, 3))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = type(exc).__name__ + ": " + str(exc)[:200]
                finished.set()

    watcher = asyncio.create_task(monitor())
    consumer = asyncio.create_task(stream())
    await finished.wait()
    consumer.cancel()
    watcher.cancel()
    await asyncio.gather(consumer, watcher, return_exceptions=True)
    save()
    print(json.dumps({"phase": state.get("phase"), "counts": dict(counts), "error": error}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--soak", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
