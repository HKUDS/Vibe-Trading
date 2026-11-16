"""One real client mixes markets/products/horizons while consuming live SSE.

Run against the isolated soak server. Crypto is upstream WebSocket; client
transport is SSE. Stocks/options remain explicitly polled/delayed snapshots.
No prices are retained in the evidence report.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import httpx


async def run(args):
    """Record every outcome, including partial responses and injected outages."""
    url = f"http://127.0.0.1:{args.port}"
    started = time.monotonic()
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "requests": [], "streams": {}, "faults": []}
    topics = [
        "crypto:BTC-USDT",
        "crypto:ETH-USDT",
        "options:AAPL",
        "options:SPY",
        "bars:000001.SZ:1D",
        "bars:000001.SZ:1W",
    ]
    specs = {
        "six_market_daily": {
            "codes": ["AAPL.US", "00700.HK", "TD.TO", "VOD.L", "601398.SH", "BTC-USDT"],
            "start_date": "2026-10-15",
            "end_date": "2026-11-13",
            "interval": "1D",
        },
        "five_year_monthly": {
            "codes": ["AAPL.US", "MSFT.US"],
            "start_date": "2021-11-14",
            "end_date": "2026-11-13",
            "interval": "1M",
        },
        "us_one_day_minute": {
            "codes": ["AAPL.US", "MSFT.US"],
            "start_date": "2026-11-12",
            "end_date": "2026-11-12",
            "interval": "1m",
        },
    }

    def save():
        report["elapsed_s"] = round(time.monotonic() - started, 3)
        args.output.write_text(json.dumps(report, indent=2))

    save()
    async with httpx.AsyncClient(timeout=25, limits=httpx.Limits(max_connections=10)) as client:
        discovery = (await client.get(url + "/data/options", params={"ticker": "AAPL", "full": "true"})).json()
        expirations = discovery.get("data", {}).get("expirations", [])
        report["aapl_discovered_expirations"] = expirations
        option_requests = [
            ("options_AAPL", {"ticker": "AAPL", "full": "true"}),
            ("options_SPY", {"ticker": "SPY", "full": "true"}),
        ]
        if len(expirations) > 1:
            option_requests.append(
                ("options_AAPL_next", {"ticker": "AAPL", "full": "true", "expiration": expirations[1]})
            )

        async def fetch(label, method, path, round_number, **kwargs):
            stamp = time.monotonic()
            item = {"label": label, "round": round_number, "start_s": round(stamp - started, 3)}
            try:
                response = await client.request(method, url + path, **kwargs)
                value = response.json()
                item.update(
                    status=response.status_code,
                    ok=value.get("ok"),
                    gateway=value.get("gateway"),
                    error=value.get("error", value.get("detail")),
                )
                if "codes" in kwargs.get("json", {}):
                    spec = kwargs["json"]
                    data = value.get("data", {})
                    item.update(spec=spec, complete=value.get("complete"), missing=data.get("_unresolved"), series={})
                    for symbol in spec["codes"]:
                        rows = data.get(symbol, [])
                        sampled = isinstance(rows, dict)
                        if sampled:
                            rows = rows.get("data", [])
                        stamps = [row.get("trade_date") for row in rows]
                        item["series"][symbol] = {
                            "rows": len(rows),
                            "sampled": sampled,
                            "first": min(stamps) if stamps else None,
                            "last": max(stamps) if stamps else None,
                            "provenance": data.get("_provenance", {}).get(symbol),
                            "coverage": data.get("_coverage", {}).get(symbol),
                        }
                elif label.startswith("options_"):
                    data = value.get("data", {})
                    item.update(
                        ticker=data.get("ticker"),
                        expiration=data.get("expiration"),
                        contracts=len(data.get("calls", [])) + len(data.get("puts", [])),
                        source=value.get("source"),
                        requested_expiration=kwargs["params"].get("expiration"),
                        contract_expirations=sorted(
                            {row.get("expiration") for side in ("calls", "puts") for row in data.get(side, [])}
                        ),
                        identity_valid=(
                            data.get("ticker") == kwargs["params"]["ticker"]
                            and (
                                "expiration" not in kwargs["params"]
                                or data.get("expiration") == kwargs["params"]["expiration"]
                            )
                        )
                        if value.get("ok")
                        else None,
                    )
                else:
                    rows = value.get("rows", [])
                    item.update(
                        rows=len(rows),
                        sampled=value.get("sampled"),
                        next_offset=value.get("next_offset"),
                        first=rows[0].get("time") if rows else None,
                        last=rows[-1].get("time") if rows else None,
                        note=(
                            "Completed dataset: unsampled production page"
                            if label == "completed_history_page"
                            else "Capability probe: unfinished datasets currently refuse prefix reads with 409"
                        ),
                    )
            except Exception as exc:
                item["client_error"] = type(exc).__name__
            item["seconds"] = round(time.monotonic() - stamp, 3)
            report["requests"].append(item)
            save()

        async def consume():
            try:
                async with asyncio.timeout(args.seconds):
                    async with client.stream(
                        "GET", url + "/data/stream", params={"topics": ",".join(topics)}, timeout=None
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            event = json.loads(line[6:])
                            payload = event.get("payload", {})
                            meta = payload.get("gateway", {})
                            row = report["streams"].setdefault(
                                event["topic"],
                                {"snapshots": 0, "errors": 0, "transports": {}, "qualities": {}, "sources": {}},
                            )
                            row["snapshots" if event["event"] == "snapshot" else "errors"] += 1
                            for key, value in [
                                ("transports", meta.get("transport", "unknown")),
                                ("qualities", meta.get("quality", "unknown")),
                                ("sources", payload.get("source", "unknown")),
                            ]:
                                row[key][value] = row[key].get(value, 0) + 1
                            row["last_received_s"] = round(time.monotonic() - started, 3)
                            row["last_acquired_at"] = meta.get("fetched_at")
                            row["last_source_time_ms"] = payload.get("data", {}).get("source_time_ms")
                            row["last_provenance"] = payload.get("data", {}).get("_provenance")
                            row["last_quote_currency"] = payload.get("data", {}).get("quote_currency")
            except TimeoutError:
                pass
            except Exception as exc:
                report["stream_error"] = type(exc).__name__

        stream = asyncio.create_task(consume())
        for round_number in range(4):
            if args.follow_faults:
                wanted = ("online", "ws_offline", "all_offline", "online")[round_number]
                while True:
                    metrics = (await client.get(url + "/_soak/metrics")).json()
                    if metrics["fault"] == wanted:
                        break
                    if time.monotonic() - started >= args.seconds - 25:
                        raise TimeoutError("Soak did not reach the requested fault round before the stream deadline")
                    await asyncio.sleep(2)
            else:
                await asyncio.sleep(max(0, started + round_number * args.seconds / 4 - time.monotonic()))
                metrics = (await client.get(url + "/_soak/metrics")).json()
            report["faults"].append(
                {"round": round_number, "mode": metrics["fault"], "elapsed_s": time.monotonic() - started}
            )
            await asyncio.gather(
                *(
                    fetch(label, "POST", "/data/bars", round_number, json={**spec, "max_rows": 1000})
                    for label, spec in specs.items()
                ),
                *(
                    fetch(
                        label,
                        "GET",
                        "/data/options",
                        round_number,
                        params=parameters,
                    )
                    for label, parameters in option_requests
                ),
                *(
                    [
                        fetch(
                            "completed_history_page",
                            "GET",
                            f"/data/history/jobs/{args.completed_job}/rows",
                            round_number,
                            params={"offset": round_number * 100, "limit": 1000},
                        )
                    ]
                    if args.completed_job
                    else []
                ),
                fetch(
                    "large_history_prefix",
                    "GET",
                    f"/data/history/jobs/{args.job}/rows",
                    round_number,
                    params={"offset": 0, "limit": 1000},
                ),
            )
        await stream
    report["complete"] = True
    report["method"] = (
        "One concurrent HTTP/SSE client during the running 64-topic mixed soak; no source/size/concurrency limit overrides"
    )
    save()
    print(
        json.dumps(
            {
                "output": str(args.output),
                "requests": len(report["requests"]),
                "streams": len(report["streams"]),
                "elapsed_s": report["elapsed_s"],
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8913)
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument(
        "--follow-faults", action="store_true", help="Follow the driver's actual online/WS/offline/recovery transitions"
    )
    parser.add_argument("--job", required=True)
    parser.add_argument("--completed-job")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        report = json.loads(args.output.read_text()) if args.output.exists() else {}
        report.update(complete=False, terminal_error=type(exc).__name__, terminal_message=str(exc)[:200])
        args.output.write_text(json.dumps(report, indent=2))
        raise


if __name__ == "__main__":
    main()
