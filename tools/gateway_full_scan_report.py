"""Summarize full-scan coverage, acquisition pressure and whole-process memory."""

import argparse
import json
from pathlib import Path
import statistics

MIB = 2**20


def distribution(values):
    """Return bounded descriptive statistics for recorded scalar observations."""
    ordered = sorted(values)
    if not ordered:
        return None
    return {"count": len(ordered), "median": statistics.median(ordered),
            "p95": ordered[int((len(ordered) - 1) * .95)], "min": ordered[0], "max": ordered[-1]}


def slope(rows, key):
    """Measure OLS memory slope in MiB/minute, without declaring a leak threshold."""
    if len(rows) < 2:
        return None
    xs = [r["elapsed_seconds"] / 60 for r in rows]
    ys = [r[key] / MIB for r in rows]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx)**2 for x in xs)


def partition_bars(trace, scan_final=None):
    """Separate scan requests from historical failover, then reconcile totals.

    Legacy v21 traces lack request parameters. Their failed exact-source
    single-symbol history requests have one distinct diagnostic source. Auto
    scan failures exhaust multiple sources; deadline failures stay scan events.
    The final queue counters must match all three independent totals, otherwise
    this inference is refused. New traces carry interval/source explicitly.
    """
    scan, history = [], []
    for row in trace:
        if row["event"] != "bars":
            continue
        sources = {a["source"] for steps in row.get("diagnostics", {}).values() for a in steps}
        if "interval" in row:
            historical = row["interval"] != "1D" or row.get("requested_source", "auto") != "auto"
        else:
            historical = (len(row["codes"]) == 1 and not row["ok"]
                          and row.get("error") == "No compatible source returned data" and len(sources) == 1)
        (history if historical else scan).append(row)
    if scan_final:
        assert len(scan) == scan_final["batches"], "Ambiguous trace classification: batch count differs"
        assert sum(len(r["codes"]) for r in scan) == scan_final["attempts"], "Request identity count differs"
        missing = sum(len(set(r["codes"]) - set(r["returned"])) for r in scan)
        assert missing == scan_final["retries"] + scan_final["failed"], "Missing identity count differs"
    return scan, history


def summarize(root, output):
    """Write quarter-by-progress evidence, preserving all first-attempt failures.

    Args:
        root: Probe output directory containing samples and traces.
        output: Outside-checkout directory for summary and plots.
    """
    report = json.loads((root / "report.json").read_text())
    samples = [json.loads(line) for line in (root / "samples.jsonl").read_text().splitlines()]
    trace = [json.loads(line) for line in (root / "scan-trace.jsonl").read_text().splitlines()]
    batches, history_bars = partition_bars(trace, report.get("scan_final"))
    active = [s for s in samples if s["phase"] == "active"]
    # Recover the wall-clock origin from the driver's atomic report write.
    # Cuts use the first ~2-second status sample past each completion threshold.
    origin = (root / "report.json").stat().st_mtime - report["elapsed_seconds"]
    cuts = [0] + [next((s["elapsed_seconds"] for s in active if s["scan"]["completed"] >= q * 5224 / 4), float("inf"))
                  for q in range(1, 4)] + [float("inf")]
    quarters = []
    for q in range(4):
        group = [s for s in active if min(3, s["scan"]["completed"] * 4 // 5224) == q]
        calls = [b for b in batches if cuts[q] <= b["time"] - origin < cuts[q + 1]]
        quarters.append({"quarter": q + 1, "samples": len(group), "completed_requests": len(calls),
            "request_seconds": distribution([b["elapsed"] for b in calls]),
            "requests_with_missing_symbols": sum(set(b["codes"]) != set(b["returned"]) for b in calls),
            "request_timeouts": sum("timed out" in str(b.get("error", "")) for b in calls),
            "requests_with_source_timeout_diagnostic": sum(
                any(a.get("reason") == "timeout" for attempts in b.get("diagnostics", {}).values() for a in attempts)
                for b in calls),
            "successful_request_seconds": distribution([b["elapsed"] for b in calls if set(b["codes"]) == set(b["returned"])]),
            "tree_footprint_mib": distribution([s["tree_footprint_bytes"] / MIB for s in group]),
            "tree_rss_mib": distribution([s["tree_rss_bytes"] / MIB for s in group]),
            "tree_footprint_slope_mib_per_minute": slope(group, "tree_footprint_bytes"),
            "active_history_jobs": distribution([sum(j["state"] in {"running", "waiting", "queued"} for j in s["jobs"]) for s in group]),
            "history_chunks": [sum(j["completed_chunks"] for j in s["jobs"]) for s in (group[:1] + group[-1:])],
            "stream_events": [sum(x["events"] for x in s["streams"]) for s in (group[:1] + group[-1:])]})
    late = [s for s in active if s["scan"]["completed"] >= 2612]
    result = {"phase": report["phase"], "scan_final": report.get("scan_final"), "errors": report["errors"],
        "scan_requests": len(batches), "historical_fallback_requests": len(history_bars),
        "queue_counters_reconciled": bool(report.get("scan_final")),
        "quarters": quarters, "late_tree_slope_mib_per_minute": slope(late, "tree_footprint_bytes"),
        "peak_tree_footprint_mib": max(s["tree_footprint_bytes"] for s in samples) / MIB,
        "peak_tree_rss_mib": max(s["tree_rss_bytes"] for s in samples) / MIB,
        "final_tree_footprint_mib": samples[-1]["tree_footprint_bytes"] / MIB,
        "final_tree_rss_mib": samples[-1]["tree_rss_bytes"] / MIB,
        "final_cache": samples[-1]["gateway"]["cache"],
        "notes": ["OS parent plus observed descendants; controller excluded; no forced GC or tracemalloc",
                  "Memory slope is measured evidence, not a universal leak/no-leak assertion",
                  "Request/memory quarters use completed-scan progress, with cuts at the first sampled threshold crossing",
                  "First-attempt omissions remain counted even if the scanner later fills them"]}
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(result, indent=2))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    xs = [s["elapsed_seconds"] / 60 for s in samples]
    axes[0].plot(xs, [s["tree_footprint_bytes"] / MIB for s in samples], label="Process tree physical footprint")
    axes[0].plot(xs, [s["tree_rss_bytes"] / MIB for s in samples], label="Process tree RSS", alpha=.65)
    axes[0].set_ylabel("MiB")
    axes[0].legend()
    axes[1].plot([s["elapsed_seconds"] / 60 for s in active], [s["scan"]["completed"] for s in active], label="Scan completed")
    axes[1].plot([s["elapsed_seconds"] / 60 for s in active], [s["scan"]["retries"] for s in active], label="Scan symbol retries")
    axes[1].set_ylabel("Symbols")
    axes[1].legend()
    axes[2].plot(xs, [sum(j["completed_chunks"] for j in s["jobs"]) for s in samples], label="Retained history chunks")
    axes[2].set_ylabel("Chunks")
    axes[2].set_xlabel("Elapsed minutes")
    axes[2].legend()
    for axis in axes:
        axis.grid(alpha=.2)
    figure.suptitle("Full 5,224-symbol scan with real subscriptions and historical downloads")
    figure.tight_layout()
    figure.savefig(output / "memory-and-progress.png", dpi=150)
    plt.close(figure)
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.root, args.output)
