"""Measure existing public routes through an already-running isolated soak API.

Waits for online windows; records requested AND actual source, since an explicit
preferred source can fall back. Retains metadata only, never price payloads.
"""

import argparse
import asyncio
from datetime import date, timedelta
import json
from pathlib import Path
import time

import httpx
from backtest.loader_health import CANARY_SYMBOLS


async def run(args):
    results = []
    async with httpx.AsyncClient(timeout=22) as client:
        for source, symbol in CANARY_SYMBOLS.items():
            if source == "baostock":
                symbol = "601398.SH"
            for attempt in range(2):
                while True:
                    report = json.loads(args.soak.read_text())
                    transition = report["transitions"][-1] if report["transitions"] else None
                    if report["phase"] == "complete":
                        raise RuntimeError("Soak completed before route probes")
                    if (
                        transition
                        and report["phase"] == "online"
                        and report["elapsed_s"] - transition["elapsed_s"] < 10
                    ):
                        break
                    await asyncio.sleep(2)
                body = {
                    "codes": [symbol],
                    "source": source,
                    "interval": "1D",
                    "max_rows": 211 + attempt,
                    "start_date": str(date.today() - timedelta(days=21)),
                    "end_date": str(date.today()),
                }
                start_transition = transition
                for repeat in (False, True):
                    stamp = time.monotonic()
                    response = await client.post(args.url + "/data/bars", json=body)
                    elapsed = (time.monotonic() - stamp) * 1000
                    payload = response.json()
                    report = json.loads(args.soak.read_text())
                    row = {
                        "source_requested": source,
                        "symbol": symbol,
                        "attempt": attempt,
                        "repeat": repeat,
                        "latency_ms": round(elapsed, 3),
                        "http_status": response.status_code,
                        "ok": payload.get("ok"),
                        "complete": payload.get("complete"),
                        "gateway": payload.get("gateway"),
                        "provenance": payload.get("data", {}).get("_provenance"),
                        "diagnostics": payload.get("data", {}).get("_diagnostics"),
                        "error": payload.get("error"),
                        "cycle": start_transition["cycle"],
                        "fault_crossed": report["transitions"][-1] != start_transition,
                    }
                    # Compare only transition identity: delivery metadata can change while online.
                    last = report["transitions"][-1]
                    row["fault_crossed"] = (last["elapsed_s"], last["mode"]) != (
                        start_transition["elapsed_s"],
                        start_transition["mode"],
                    )
                    results.append(row)
                    args.output.write_text(json.dumps({"phase": "running", "results": results}, indent=2))
                    print(
                        json.dumps(
                            {
                                k: row[k]
                                for k in ("source_requested", "repeat", "latency_ms", "http_status", "fault_crossed")
                            }
                        ),
                        flush=True,
                    )
                if not results[-1]["fault_crossed"]:
                    break
    args.output.write_text(json.dumps({"phase": "complete", "results": results}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--soak", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
