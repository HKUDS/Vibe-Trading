"""Live, unsampled verification of a completed history job; metadata report only.

PYTHONPATH=agent python tools/gateway_history_validate.py --root <outside-repo>
    --job <id> --output /tmp/history-verification.json
Re-queries BaoStock's full-range daily status and calendar independently of the
monthly downloads, verifies every compressed chunk, then reads every API page.
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import time

from gateway_capacity_probe import memory
from src.data_gateway.history_store import HistoryStore


def verify(store, job):
    """Cross-check complete data against fresh daily/calendar queries and paging."""
    import baostock as bs
    from backtest.loaders.baostock_loader import _baostock_socket_guard, _read_timeout

    state = store.status(job)
    if state["state"] != "complete":
        raise ValueError("Cannot certify an incomplete job")
    spec = state["spec"]
    start, end = spec["start_date"], spec["end_date"]
    frequency = {"5m": 5, "15m": 15, "30m": 30, "1H": 60}[spec["interval"]]

    def records(result):
        data = []
        while result.error_code == "0" and result.next():
            data.append(dict(zip(result.fields, result.get_row_data(), strict=True)))
        if result.error_code != "0":
            raise ValueError("Independent source query failed: " + result.error_code)
        return data

    report = {"job": job, "spec": spec, "symbols": [], "samples": [], "started_at": datetime.now().isoformat()}
    expected = {}
    with _baostock_socket_guard(_read_timeout()) as acquired:
        if not acquired or bs.login().error_code != "0":
            raise ValueError("Independent source login unavailable")
        try:
            calendar = records(bs.query_trade_dates(start_date=start, end_date=end))
            if len(calendar) != (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days + 1:
                raise ValueError("Incomplete independent calendar")
            sessions = {r["calendar_date"] for r in calendar if r["is_trading_day"] == "1"}
            for symbol in spec["codes"]:
                code, venue = symbol.split(".")
                daily = records(
                    bs.query_history_k_data_plus(
                        venue.lower() + "." + code,
                        "date,code,tradestatus",
                        start_date=start,
                        end_date=end,
                        frequency="d",
                        adjustflag="3",
                    )
                )
                if len(daily) != len(sessions) or {r["date"] for r in daily} != sessions:
                    raise ValueError("Independent daily calendar mismatch: " + symbol)
                expected[symbol] = {r["date"]: 240 // frequency for r in daily if r["tradestatus"] == "1"}
        finally:
            bs.logout()
    all_digest = hashlib.sha256()
    for symbol in spec["codes"]:
        counts, previous, first, n = Counter(), None, None, 0
        for chunk in (c for c in state["chunks"] if c["symbol"] == symbol):
            with store.transaction() as db:
                digest = db.execute("SELECT digest FROM chunks WHERE job=? AND idx=?", (job, chunk["idx"])).fetchone()[
                    0
                ]
            path = store._path(job, chunk["idx"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("Chunk digest mismatch")
            with gzip.open(path, "rt") as stream:
                for line in stream:
                    row = json.loads(line)
                    stamp = row["time"]
                    if row["symbol"] != symbol or (previous and stamp <= previous):
                        raise ValueError("Identity, duplicate or ordering mismatch")
                    point = datetime.fromisoformat(stamp)
                    allowed = set()
                    for hour, minute in ((9, 30), (13, 0)):
                        base = point.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        allowed.update(base + timedelta(minutes=m) for m in range(frequency, 121, frequency))
                    if point not in allowed:
                        raise ValueError("Unexpected intraday timestamp")
                    counts[stamp[:10]] += 1
                    first = first or stamp
                    previous = stamp
                    n += 1
                    all_digest.update((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode())
        if dict(counts) != expected[symbol]:
            raise ValueError("Full five-year daily/minute coverage mismatch: " + symbol)
        report["symbols"].append(
            {"symbol": symbol, "rows": n, "sessions": len(counts), "first": first, "last": previous}
        )
        report["samples"].append(memory())
    # Exercise the actual public paged store reader, including chunk boundaries.
    page_digest, offset, pages = hashlib.sha256(), 0, 0
    while True:
        page = store.read(job, offset, 1000)
        if page["sampled"] or not page["rows"]:
            raise ValueError("Empty or sampled page")
        for row in page["rows"]:
            page_digest.update((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode())
        pages += 1
        if page["next_offset"] is None:
            offset += len(page["rows"])
            break
        offset = page["next_offset"]
    if page_digest.digest() != all_digest.digest() or offset != state["rows"]:
        raise ValueError("Paged read omitted, duplicated or changed rows")
    report.update(
        verified=True,
        total_rows=offset,
        chunks=state["total_chunks"],
        pages=pages,
        canonical_sha256=all_digest.hexdigest(),
        storage=store.settings(),
        final_memory=memory(),
    )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    store = HistoryStore(args.root)
    started = time.monotonic()
    try:
        report = verify(store, args.job)
        report["verification_seconds"] = round(time.monotonic() - started, 2)
        args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps({k: v for k, v in report.items() if k not in {"samples", "symbols"}}))
    finally:
        store.close()


if __name__ == "__main__":
    main()
