"""Opt-in public-data HSI coverage check; never runs factors, orders or collectors."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.tools import alpha_bench_tool as bench
from src.tools.hsi_universe import (
    HSIConstituentError,
    REFERENCE_CODES,
    REFERENCE_EFFECTIVE_DATE,
    REFERENCE_SOURCE_URL,
    REFERENCE_SNAPSHOT_DATE,
)


def coverage(panel: dict) -> dict:
    """Export counts/provenance only, never raw bars or runtime account settings."""
    close = panel["close"]
    meta = panel["_meta"]
    return {
        "requested": meta["requested_instruments"],
        "fetched": meta["fetched_instruments"],
        "missing_symbols": meta["missing_instruments"],
        "observed_dates": len(close),
        "first_date": str(close.index.min().date()),
        "last_date": str(close.index.max().date()),
        "close_observations": int(close.notna().sum().sum()),
        "per_symbol_close_observations": {str(c): int(close[c].notna().sum()) for c in close},
        "missing_cells": meta["missing_observations"],
        "sources": meta["price_sources"],
        "price_adjustments": meta["price_adjustments"],
        "volume_units": meta["volume_units"],
        "quality_warnings": meta["data_quality_warnings"],
        "missing_data_policy": meta["missing_data_policy"],
    }


def run(start: str, end: str, *, reference_diagnostic: bool = False) -> dict:
    """Call the real benchmark path and optionally inspect dated-reference prices.

    The reference diagnostic never enters the benchmark runner or its price
    cache and is explicitly ineligible. A working price source cannot validate
    an invalid primary-source membership list.
    """
    bench._parse_period(f"{start}/{end}")
    report = {
        "schema": "hsi-universe-smoke/v1",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "period": {"start": start, "end": end},
        "membership_policy": "strict_dated_reference_v4",
        "benchmark_usable": False,
        "reference_effective_date": REFERENCE_EFFECTIVE_DATE,
        "reference_snapshot_date": REFERENCE_SNAPSHOT_DATE,
        "reference_source": REFERENCE_SOURCE_URL,
    }
    try:
        panel = bench._load_universe_panel("hsi", f"{start}/{end}", use_cache=False)
        prices = coverage(panel)
        report["primary"] = {
            "status": "loaded",
            "constituents": {k: v for k, v in panel["_meta"].items() if k.startswith("constituent_")},
            "prices": prices,
        }
        report["benchmark_usable"] = True
        report["price_coverage_complete"] = not prices["missing_symbols"]
    except HSIConstituentError as exc:
        report["primary"] = {
            "status": "blocked",
            "error": str(exc),
            "constituents": exc.metadata,
            "prices": {"status": "not_attempted", "reason": "Constituent validation failed before price access"},
        }
    except (ValueError, RuntimeError):
        report["primary"] = {
            "status": "price_load_failed",
            "error": "Price path failed; inspect provider availability, period and dependencies.",
        }
    if reference_diagnostic:
        metadata = {
            "constituent_source": REFERENCE_SOURCE_URL,
            "constituent_source_date": REFERENCE_SNAPSHOT_DATE,
            "degraded": True,
            "benchmark_eligible": False,
            "inspection_only": True,
        }
        try:
            panel = bench._load_hsi_panel(start, end, constituents=(list(REFERENCE_CODES), {}, metadata))
            report["reference_price_diagnostic"] = {
                "status": "loaded",
                "benchmark_eligible": False,
                "note": "Explicit dated-reference inspection, not a primary-source fallback or benchmark result.",
                "prices": coverage(panel),
            }
        except (ValueError, RuntimeError):
            report["reference_price_diagnostic"] = {
                "status": "failed",
                "benchmark_eligible": False,
                "error": "Dated-reference price inspection failed; no success or coverage inferred.",
            }
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    return report


def main() -> None:
    """Run only after explicit invocation; exit nonzero when production is blocked."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-diagnostic", action="store_true")
    args = parser.parse_args()
    result = run(args.start, args.end, reference_diagnostic=args.reference_diagnostic)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"benchmark_usable": result["benchmark_usable"], "report": str(args.output)}, indent=2))
    raise SystemExit(0 if result["benchmark_usable"] else 1)


if __name__ == "__main__":
    main()
