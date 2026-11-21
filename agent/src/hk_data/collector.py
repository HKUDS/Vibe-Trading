"""Command-line continuous collection of Hong Kong quote snapshots."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.hk_data.service import (
    DEFAULT_SYMBOLS,
    SOURCES,
    fetch_quotes,
    iso_time,
    normalize_symbols,
)
from src.hk_data.storage import QuoteStore


def load_symbols(path: Path) -> list[str]:
    """Read a selected HK universe without requiring bundled market files."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        if path.suffix.lower() == ".csv":
            reader = csv.DictReader(handle)
            column = next(
                (
                    name
                    for name in ("ticker", "yahoo_ticker", "symbol")
                    if name in (reader.fieldnames or [])
                ),
                None,
            )
            if column is None:
                raise ValueError("CSV needs a ticker, yahoo_ticker or symbol column")
            symbols = [
                (row.get(column) or "").strip()
                for row in reader
                if (row.get(column) or "").strip()
            ]
        else:
            symbols = [
                line.strip()
                for line in handle
                if line.strip() and not line.lstrip().startswith("#")
            ]
    return normalize_symbols(symbols)


def collect(
    store: QuoteStore,
    symbols: list[str],
    *,
    source: str = "auto",
    interval_seconds: float = 60,
    cycles: int | None = None,
    retain_days: int = 30,
    max_age_seconds: float = 1200,
    fetcher: Callable = fetch_quotes,
    sleeper: Callable = time.sleep,
    emit: Callable = print,
) -> dict:
    """Poll until interrupted, saving health even during provider outages."""
    failures, count = 0, 0
    while True:
        started = time.monotonic()
        try:
            result = fetcher(symbols, source=source, max_age_seconds=max_age_seconds)
        except Exception as exc:
            result = {
                "ok": False,
                "status": "error",
                "observed_at_utc": iso_time(datetime.now(timezone.utc)),
                "quotes": [],
                "missing": symbols,
                "errors": [
                    {
                        "error": type(exc).__name__,
                        "message": "Provider poll failed; collector will retry.",
                    }
                ],
            }
        inserted = store.record_poll(result)
        store.prune(retain_days)
        count += 1
        failures = 0 if result.get("ok") else min(failures + 1, 6)
        emit(
            json.dumps(
                {
                    "poll": count,
                    "observed_at_utc": result["observed_at_utc"],
                    "status": result["status"],
                    "quote_count": len(result["quotes"]),
                    "missing_count": len(result.get("missing", [])),
                    "new_revisions": inserted,
                    "stale_count": sum(
                        row["status"] == "stale" for row in result["quotes"]
                    ),
                    "db": str(store.path),
                },
                allow_nan=False,
            ),
            flush=True,
        )
        if cycles is not None and count >= cycles:
            return result
        # The interval includes request duration. Entire failed polls back off
        # up to five minutes; successful recovery resets the delay.
        delay = (
            min(max(interval_seconds, 300.0), interval_seconds * 2**failures)
            if failures
            else interval_seconds
        )
        sleeper(max(0.0, delay - (time.monotonic() - started)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    universe = parser.add_mutually_exclusive_group()
    universe.add_argument("--symbols", nargs="+")
    universe.add_argument("--symbols-file", type=Path)
    universe.add_argument(
        "--hsi-snapshot",
        action="store_true",
        help="Use the dated 2026-11-04 HSI 95-stock snapshot; refresh after index reviews",
    )
    parser.add_argument("--source", choices=SOURCES, default="tencent")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--interval-seconds", type=float, default=5)
    parser.add_argument("--max-age-seconds", type=float, default=60)
    parser.add_argument("--retain-days", type=int, default=30)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--cycles", type=int)
    mode.add_argument("--latest", action="store_true")
    args = parser.parse_args(argv)
    if not math.isfinite(args.interval_seconds) or args.interval_seconds < 5:
        parser.error("--interval-seconds must be at least 5")
    if not math.isfinite(args.max_age_seconds) or args.max_age_seconds <= 0:
        parser.error("--max-age-seconds must be positive")
    if args.retain_days < 0 or (args.cycles is not None and args.cycles < 1):
        parser.error("--retain-days must be nonnegative and --cycles must be positive")
    try:
        symbols = (
            load_symbols(args.symbols_file)
            if args.symbols_file
            else normalize_symbols(args.symbols) if args.symbols else None
        )
        if args.hsi_snapshot:
            from src.tools.hsi_universe import FALLBACK_CODES, FALLBACK_DATE

            symbols = normalize_symbols(FALLBACK_CODES)
            print(
                f"Using dated HSI roster {FALLBACK_DATE}: {len(symbols)} stocks; refresh after index reviews.",
                file=sys.stderr,
            )
        with QuoteStore(args.db, readonly=args.latest) as store:
            if args.latest:
                print(
                    json.dumps(
                        store.latest(symbols, max_age_seconds=args.max_age_seconds),
                        indent=2,
                        allow_nan=False,
                    )
                )
                return 0
            result = collect(
                store,
                symbols or DEFAULT_SYMBOLS,
                source=args.source,
                interval_seconds=args.interval_seconds,
                cycles=1 if args.once else args.cycles,
                retain_days=args.retain_days,
                max_age_seconds=args.max_age_seconds,
            )
            return 0 if result.get("ok") else 1
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
