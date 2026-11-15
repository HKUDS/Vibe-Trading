"""Live capacity validation: topic admission, 64-topic refresh, SH/SZ scanning.

Uses real production routes, isolated servers and temporary caches. Only symbol
identities, counts, errors and resource/timing metadata are persisted, no prices.
"""

import argparse
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

import httpx


def universe():
    """Read the settled BaoStock SH/SZ A-share universe; Beijing is excluded."""
    import baostock as bs
    from backtest.loaders.baostock_loader import _baostock_socket_guard, _read_timeout
    from src.data_gateway.history_source import _sdk_output

    day = str(date.today() - timedelta(days=1))
    with _baostock_socket_guard(_read_timeout()) as acquired, _sdk_output():
        if not acquired or bs.login().error_code != "0":
            raise RuntimeError("Universe login unavailable")
        try:
            calendar = bs.query_trade_dates(start_date=str(date.today() - timedelta(days=14)), end_date=day)
            settled = []
            while calendar.error_code == "0" and calendar.next():
                item = dict(zip(calendar.fields, calendar.get_row_data(), strict=True))
                if item["is_trading_day"] == "1":
                    settled.append(item["calendar_date"])
            if calendar.error_code != "0" or not settled:
                raise RuntimeError("Settled trading calendar unavailable")
            day = max(settled)
            result = bs.query_all_stock(day=day)
            codes = []
            total = 0
            while result.error_code == "0" and result.next():
                row = dict(zip(result.fields, result.get_row_data(), strict=True))
                total += 1
                code = row["code"]
                if re.fullmatch(r"(?:sh\.(?:60|68)|sz\.(?:00|30))\d{4}", code):
                    venue, number = code.split(".")
                    codes.append(number + "." + venue.upper())
            if result.error_code != "0" or not codes:
                raise RuntimeError("Universe query incomplete")
            codes = sorted(set(codes))
            return {
                "source": "baostock.query_all_stock",
                "date": day,
                "scope": "SH/SZ A-share codes 60/68/00/30; excludes Beijing, ETFs, indices and B-shares",
                "source_rows": total,
                "codes": codes,
                "sha256": hashlib.sha256("\n".join(codes).encode()).hexdigest(),
            }
        finally:
            bs.logout()


def screeners():
    """Exercise the existing agent-facing whole-market ranking tool unchanged."""
    from src.tools.market_screener_tool import MarketScreenerTool
    from backtest.loader_health import sanitize_evidence

    rows = []
    for market in ("a", "us", "hk"):
        stamp = time.monotonic()
        result = json.loads(MarketScreenerTool().execute(market=market, top_n=100))
        rows.append(
            {
                "market": market,
                "ok": result.get("ok"),
                "source": result.get("source"),
                "rows": len(result.get("data", {}).get("rows", [])),
                "ms": round((time.monotonic() - stamp) * 1000, 3),
                "error": sanitize_evidence(result.get("error", "")),
                "gateway_integrated": False,
            }
        )
    return rows


async def run(args):
    document = {"started_utc": datetime.now(timezone.utc).isoformat(), "phase": "universe", "stages": []}

    def save():
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, indent=2))
        temporary.replace(args.output)

    document["universe"] = await asyncio.to_thread(universe)
    save()
    all_codes = document["universe"]["codes"]
    chosen = [
        "601398.SH",
        "600519.SH",
        "601318.SH",
        "600036.SH",
        "600000.SH",
        "601288.SH",
        "601988.SH",
        "000001.SZ",
        "000002.SZ",
        "000333.SZ",
    ]
    chosen += [code for code in all_codes if code not in chosen][: 32 - len(chosen)]
    if any(code not in all_codes for code in chosen):
        raise RuntimeError("Watchlist is not in the actual universe")
    topics = [f"bars:{code}:{interval}" for code in chosen for interval in ("1D", "1W")]
    url = f"http://127.0.0.1:{args.port}"

    @asynccontextmanager
    async def server(limit):
        with tempfile.TemporaryDirectory(prefix="vibe-gateway-scale-cache-") as cache:
            env = dict(
                os.environ,
                VIBE_GATEWAY_CACHE_DIR=cache,
                VIBE_GATEWAY_STREAM_TOPICS=str(limit),
                VIBE_TRADING_DATA_CACHE="0",
            )
            env.pop("VIBE_GATEWAY_TRACE_DIR", None)
            env.pop("VIBE_GATEWAY_SOAK_HISTORY", None)
            log = args.output.with_suffix(f".{limit}.log")
            with log.open("w") as handle:
                child = subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).with_name("gateway_soak.py")),
                        "--server",
                        "--port",
                        str(args.port),
                        "--output",
                        str(args.output),
                    ],
                    env=env,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                )
                try:
                    async with httpx.AsyncClient(timeout=25, limits=httpx.Limits(max_connections=32)) as client:
                        for _ in range(120):
                            if child.poll() is not None:
                                raise RuntimeError("Scale server exited during startup")
                            try:
                                response = await client.get(url + "/_soak/metrics")
                                if response.json()["pid"] != child.pid:
                                    raise RuntimeError("Port belongs to a different process")
                                break
                            except httpx.TransportError:
                                await asyncio.sleep(1)
                        else:
                            raise RuntimeError("Scale server startup timed out")
                        yield client
                finally:
                    child.terminate()
                    try:
                        await asyncio.to_thread(child.wait, timeout=20)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        await asyncio.to_thread(child.wait)

    async def stage(limit, scan=False):
        started = time.monotonic()
        row = {
            "limit": limit,
            "requested_topics": len(topics),
            "watchlist": chosen,
            "phase": "starting",
            "samples": [],
            "topics": {},
            "connections": [],
            "scan": {"batches": [], "failed": []},
        }
        document["stages"].append(row)
        document["phase"] = f"topics_{limit}"
        async with server(limit) as client:

            async def consume(group):
                try:
                    async with client.stream(
                        "GET", url + "/data/stream", params={"topics": ",".join(group)}, timeout=None
                    ) as response:
                        entry = {"topics": group, "status": response.status_code}
                        row["connections"].append(entry)
                        if response.status_code != 200:
                            entry["error"] = (await response.aread()).decode()[:200]
                            return
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            value = json.loads(line[6:])
                            topic = value["topic"]
                            state = row["topics"].setdefault(
                                topic,
                                {
                                    "snapshots": 0,
                                    "errors": 0,
                                    "sources": [],
                                    "first_s": None,
                                    "last_s": None,
                                    "fresh_acquisitions": 0,
                                    "last_fetched_at": None,
                                },
                            )
                            elapsed = round(time.monotonic() - started, 3)
                            if value["event"] == "snapshot":
                                state["snapshots"] += 1
                                state["first_s"] = state["first_s"] if state["first_s"] is not None else elapsed
                                state["last_s"] = elapsed
                                payload = value["payload"]
                                fetched = payload.get("gateway", {}).get("fetched_at")
                                if fetched and fetched != state["last_fetched_at"]:
                                    state["fresh_acquisitions"] += 1
                                    state["last_fetched_at"] = fetched
                                for stamp in payload.get("data", {}).get("_provenance", {}).values():
                                    if stamp["source"] not in state["sources"]:
                                        state["sources"].append(stamp["source"])
                            else:
                                state["errors"] += 1
                                state["last_error"] = value["payload"].get("error")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    row.setdefault("client_errors", []).append(type(exc).__name__)

            async def scan_universe():
                queue = asyncio.Queue()
                for i in range(0, len(all_codes), 8):
                    queue.put_nowait(all_codes[i : i + 8])
                counts = Counter()
                sources = Counter()
                scan_started = time.monotonic()

                async def worker():
                    while not queue.empty():
                        codes = queue.get_nowait()
                        stamp = time.monotonic()
                        result = {"codes": codes}
                        try:
                            response = await client.post(
                                url + "/data/bars",
                                json={
                                    "codes": codes,
                                    "start_date": str(date.today() - timedelta(days=30)),
                                    "end_date": str(date.today()),
                                    "interval": "1D",
                                    "max_rows": 100,
                                },
                            )
                            payload = response.json()
                            data = payload.get("data", {})
                            received = [
                                code for code in codes if isinstance(data.get(code), list) and len(data[code]) > 0
                            ]
                            result.update(
                                status=response.status_code,
                                received=received,
                                missing=[code for code in codes if code not in received],
                                diagnostics=data.get("_diagnostics"),
                                error=payload.get("error"),
                            )
                            counts["received_symbols"] += len(received)
                            counts["rows"] += sum(len(data[code]) for code in received)
                            counts["missing_symbols"] += len(codes) - len(received)
                            for stamp_data in data.get("_provenance", {}).values():
                                sources[stamp_data["source"]] += 1
                        except Exception as exc:
                            result.update(status=None, received=[], missing=codes, error=type(exc).__name__)
                            counts["missing_symbols"] += len(codes)
                        result["ms"] = round((time.monotonic() - stamp) * 1000, 3)
                        row["scan"]["batches"].append(result)
                        row["scan"]["counts"] = dict(counts)
                        row["scan"]["sources"] = dict(sources)
                        row["scan"]["elapsed_s"] = round(time.monotonic() - scan_started, 3)
                        queue.task_done()

                await asyncio.gather(worker(), worker())
                row["scan"]["complete"] = counts["received_symbols"] == len(all_codes)
                row["scan"]["failed"] = [code for batch in row["scan"]["batches"] for code in batch["missing"]]

            tasks = [asyncio.create_task(consume(topics[i : i + 8])) for i in range(0, len(topics), 8)]
            scan_task = None
            row["phase"] = "active"
            try:
                # Observe watchlist admission and initial delivery before scanning.
                while time.monotonic() - started < (90 if scan else 45):
                    response = await client.get(url + "/_soak/metrics")
                    response.raise_for_status()
                    row["samples"].append({"elapsed_s": round(time.monotonic() - started, 3), **response.json()})
                    save()
                    await asyncio.sleep(5)
                if scan:
                    extra = next(code for code in all_codes if code not in chosen)
                    async with client.stream(
                        "GET", url + "/data/stream", params={"topics": f"bars:{extra}:1D"}
                    ) as response:
                        row["over_limit_probe"] = (
                            {"status": response.status_code, "body": (await response.aread()).decode()[:200]}
                            if response.status_code != 200
                            else {"status": 200}
                        )
                    scan_task = asyncio.create_task(scan_universe())
                    while not scan_task.done() or time.monotonic() - started < args.hold:
                        response = await client.get(url + "/_soak/metrics")
                        response.raise_for_status()
                        row["samples"].append({"elapsed_s": round(time.monotonic() - started, 3), **response.json()})
                        save()
                        await asyncio.sleep(5)
                    await scan_task
            finally:
                if scan_task and not scan_task.done():
                    scan_task.cancel()
                    await asyncio.gather(scan_task, return_exceptions=True)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            row["active_elapsed_s"] = round(time.monotonic() - started, 3)
            row["phase"] = "idle"
            deadline = time.monotonic() + (180 if scan else 5)
            while time.monotonic() < deadline:
                response = await client.get(url + "/_soak/metrics")
                response.raise_for_status()
                row["samples"].append({"elapsed_s": round(time.monotonic() - started, 3), **response.json()})
                save()
                await asyncio.sleep(5)
            row["phase"] = "complete"
            save()

    await stage(16)
    await stage(64, scan=True)
    document["screeners"] = await asyncio.to_thread(screeners)
    document["phase"] = "complete"
    save()
    print(json.dumps({"phase": "complete", "universe": len(all_codes), "report": str(args.output)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8913)
    parser.add_argument("--hold", type=float, default=600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
