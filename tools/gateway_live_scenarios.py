"""Real HTTP scenario evidence for routed data; output contains metadata, no prices."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import httpx


async def run(args):
    result = {"started_utc": datetime.now(timezone.utc).isoformat(), "scenarios": []}
    url = f"http://127.0.0.1:{args.port}"

    def save():
        args.output.write_text(json.dumps(result, indent=2))

    async with httpx.AsyncClient(timeout=25, limits=httpx.Limits(max_connections=16, keepalive_expiry=2)) as client:

        async def request(method, path, **kwargs):
            r = await client.request(method, url + path, **kwargs)
            r.raise_for_status()
            return r.json()

        async def history(spec):
            started = time.monotonic()
            job = await request("POST", "/data/history/jobs", json={**spec, "source": "auto"})
            identity = job["id"]
            await request("POST", f"/data/history/jobs/{identity}/resume")
            while time.monotonic() - started < 180:
                job = await request("GET", f"/data/history/jobs/{identity}")
                if job["state"] not in {"running", "queued"}:
                    break
                await asyncio.sleep(0.5)
            if job["state"] in {"running", "queued"}:
                await request("POST", f"/data/history/jobs/{identity}/cancel")
            pages, read_rows, previous = 0, 0, None
            if job["state"] in {"complete", "downloaded"}:
                offset = 0
                while True:
                    page = await request(
                        "GET", f"/data/history/jobs/{identity}/rows", params={"offset": offset, "limit": 1000}
                    )
                    assert not page["sampled"] and page["rows"]
                    for row in page["rows"]:
                        key = (spec["codes"].index(row["symbol"]), row["time"])
                        assert previous is None or key > previous
                        previous = key
                    pages += 1
                    read_rows += len(page["rows"])
                    if page["next_offset"] is None:
                        break
                    offset = page["next_offset"]
                assert read_rows == job["rows"]
            return {
                "spec": spec,
                "state": job["state"],
                "rows": job["rows"],
                "sources": job.get("sources"),
                "verified": job.get("coverage_verified"),
                "chunks": job["completed_chunks"],
                "total_chunks": job["total_chunks"],
                "pages_read": pages,
                "error": job.get("error"),
                "wall_s": round(time.monotonic() - started, 3),
            }

        async def bars(spec):
            started = time.monotonic()
            response = await client.post(url + "/data/bars", json=spec)
            value = response.json()
            return {
                "status": response.status_code,
                "ok": value.get("ok"),
                "complete": value.get("complete"),
                "provenance": value.get("data", {}).get("_provenance", {}),
                "missing": value.get("data", {}).get("_unresolved"),
                "gateway": value.get("gateway"),
                "error": value.get("error"),
                "ms": round((time.monotonic() - started) * 1000, 3),
            }

        async def case(number, name, action):
            if args.only and number not in args.only:
                return
            row = {"id": number, "name": name}
            try:
                row["evidence"] = await action()
                row["executed"] = True
            except Exception as exc:
                row.update(executed=False, error=f"{type(exc).__name__}: {str(exc)[:250]}")
            result["scenarios"].append(row)
            save()
            print(json.dumps({k: row[k] for k in row if k != "evidence"}), flush=True)

        await case(
            1,
            "Two US equities, five-year monthly history, all pages",
            lambda: history(
                {
                    "codes": ["AAPL.US", "MSFT.US"],
                    "start_date": "2021-11-14",
                    "end_date": "2026-11-13",
                    "interval": "1M",
                }
            ),
        )
        await case(
            2,
            "HK/Canada/UK mixed dataset, all pages",
            lambda: history(
                {
                    "codes": ["00700.HK", "TD.TO", "VOD.L"],
                    "start_date": "2026-09-01",
                    "end_date": "2026-11-13",
                    "interval": "1D",
                }
            ),
        )
        await case(
            3,
            "Two US minute series across three trading weeks",
            lambda: history(
                {
                    "codes": ["AAPL.US", "MSFT.US"],
                    "start_date": "2026-10-26",
                    "end_date": "2026-11-13",
                    "interval": "1m",
                }
            ),
        )
        await case(
            4,
            "Two continuous crypto minute grids and all pages",
            lambda: history(
                {
                    "codes": ["BTC-USDT", "ETH-USDT"],
                    "start_date": "2026-11-12",
                    "end_date": "2026-11-12",
                    "interval": "1m",
                }
            ),
        )

        async def multi_period():
            reads = []
            for interval in ("1D", "1W", "1M"):
                spec = {
                    "codes": ["AAPL.US", "MSFT.US", "NVDA.US", "AMZN.US", "GOOGL.US", "META.US", "TSLA.US", "SPY.US"],
                    "start_date": "2026-09-01",
                    "end_date": "2026-11-13",
                    "interval": interval,
                    "max_rows": 100,
                }
                reads.append({"interval": interval, "cold": await bars(spec), "repeat": await bars(spec)})
            return reads

        await case(5, "Eight equities at three periods with cold/repeat reads", multi_period)

        async def concurrent_options():
            before = await request("GET", "/_soak/metrics")
            started = time.monotonic()
            values = await asyncio.gather(
                *[request("GET", "/data/options", params={"ticker": "SPY", "full": "true"}) for _ in range(12)]
            )
            after = await request("GET", "/_soak/metrics")
            return {
                "clients": 12,
                "ok": sum(bool(v.get("ok")) for v in values),
                "source_calls": after["counts"].get("source_attempts", 0) - before["counts"].get("source_attempts", 0),
                "distinct_acquisitions": len({v.get("gateway", {}).get("fetched_at") for v in values}),
                "contracts": [{k: len(v.get("data", {}).get(k, [])) for k in ("calls", "puts")} for v in values],
                "wall_s": round(time.monotonic() - started, 3),
            }

        await case(6, "Twelve concurrent readers of full option chain", concurrent_options)

        async def partial():
            return await bars(
                {
                    "codes": [
                        "ZZZZNOTREAL.US",
                        "AAPL.US",
                        "MSFT.US",
                        "NVDA.US",
                        "SPY.US",
                        "META.US",
                        "TSLA.US",
                        "AMZN.US",
                    ],
                    "start_date": "2026-11-02",
                    "end_date": "2026-11-13",
                    "source": "yahoo",
                    "interval": "1D",
                    "max_rows": 100,
                }
            )

        await case(10, "Missing first ticker in eight-symbol real batch", partial)
        await case(
            11,
            "Explicit Stooq first, compatible fallback with provenance",
            lambda: bars(
                {
                    "codes": ["AAPL.US", "MSFT.US"],
                    "start_date": "2026-11-02",
                    "end_date": "2026-11-13",
                    "source": "stooq",
                    "interval": "1D",
                    "max_rows": 100,
                }
            ),
        )
        await case(
            21,
            "OKX daily grid including not-yet-settled UTC+8 bar",
            lambda: history(
                {
                    "codes": ["BTC-USDT", "ETH-USDT"],
                    "start_date": "2026-11-01",
                    "end_date": "2026-11-13",
                    "interval": "1D",
                }
            ),
        )
        await case(
            22,
            "Two equities, thirty years of monthly history",
            lambda: history(
                {
                    "codes": ["AAPL.US", "MSFT.US"],
                    "start_date": "1996-11-14",
                    "end_date": "2026-11-13",
                    "interval": "1M",
                }
            ),
        )
        result["final_metrics"] = await request("GET", "/_soak/metrics")
        result["completed_utc"] = datetime.now(timezone.utc).isoformat()
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8914)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", type=int, nargs="*")
    asyncio.run(run(parser.parse_args()))
