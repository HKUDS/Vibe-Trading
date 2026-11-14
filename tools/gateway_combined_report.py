"""Summarize finished live gateway soak evidence without retaining market data."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
import statistics


def distribution(values):
    """Use nearest-rank percentiles; never silently discard failed requests."""
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(values),
        "min": ordered[0],
        "p50": statistics.median(ordered),
        "p95": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "max": ordered[-1],
    }


def slope(rows, key):
    if len(rows) < 2:
        return None
    xs = [r["elapsed_s"] / 60 for r in rows]
    ys = [r[key] / 2**20 for r in rows]
    avgx, avgy = statistics.mean(xs), statistics.mean(ys)
    denominator = sum((x - avgx) ** 2 for x in xs)
    return sum((x - avgx) * (y - avgy) for x, y in zip(xs, ys)) / denominator if denominator else None


def summarize(document, observer=None):
    samples, checks = document["samples"], document["checks"]
    active = [s for s in samples if s["cycle"] >= 0 and s["phase"] != "idle"]
    start = active[0]["elapsed_s"]
    late = [s for s in active if s["elapsed_s"] - start >= 30 * 60]
    buckets = []
    duration_minutes = math.ceil((active[-1]["elapsed_s"] - start) / 60)
    for minute in range(0, duration_minutes + 1, 10):
        group = [s for s in active if minute * 60 <= s["elapsed_s"] - start < (minute + 10) * 60]
        if group:
            buckets.append(
                {
                    "active_minutes": [minute, minute + 10],
                    "samples": len(group),
                    "footprint_mib": distribution([s["footprint_bytes"] / 2**20 for s in group]),
                    "rss_mib": distribution([s["rss_bytes"] / 2**20 for s in group]),
                    "threads": distribution([s["threads"] for s in group]),
                    "fds": distribution([s["fds"] for s in group]),
                }
            )
    latencies = defaultdict(list)
    statuses = defaultdict(Counter)
    for row in checks:
        if "latency_ms" not in row:
            continue
        kind = row["kind"]
        status = row.get("status", 200 if kind == "history_page" else None)
        if status is not None:
            statuses[kind][str(status)] += 1
        cache = (row.get("gateway") or {}).get("cache", "none")
        outcome = f"http{status}:cache={cache}" if status is not None else f"state={row.get('state', 'unknown')}"
        latencies[f"{kind}:{outcome}"].append(row["latency_ms"])
    tail = samples[-1]
    last_idle = [s for s in samples if s["phase"] == "idle"]
    recovered = [c for c in checks if c["kind"] == "recovered_bar_probe"]
    offline = [c for c in checks if c["kind"] == "offline_bar_probe"]
    unexpected_http_errors = [
        c for c in checks if "latency_ms" in c and c.get("status", 200) >= 400 and c["kind"] != "offline_bar_probe"
    ]
    incomplete_bar_successes = [
        c
        for c in checks
        if c.get("request", {}).get("codes")
        and c.get("status") == 200
        and (c.get("complete") is not True or any(not row.get("rows") for row in c.get("shape", {}).values()))
    ]
    active_history = [s for s in active if any(h["state"] in {"running", "queued", "failed"} for h in s["history"])]
    result = {
        "phase": document["phase"],
        "started_utc": document["started_utc"],
        "elapsed_s": document["elapsed_s"],
        "active_elapsed_s": document["active_elapsed_s"],
        "same_pid": len({s["pid"] for s in samples}) == 1,
        "scan_job": document.get("scan_job"),
        "universe_size": len((document.get("scale_universe") or {}).get("codes", [])),
        "max_simultaneous_topics": max(len(s["subscriptions"]["topics"]) for s in samples),
        "combined_workload_samples": sum(
            len(s["subscriptions"]["topics"]) == 64
            and any(job["state"] == "running" for job in s["history"])
            and any(job["state"] == "running" for job in s["gateway"].get("scans", []))
            for s in active
        ),
        "completed_child_peak_mib": max(
            s["gateway"].get("heavy_worker", {}).get("max_completed_child_footprint_bytes", 0) for s in samples
        )
        / 2**20,
        "parent_plus_child_peak_upper_bound_mib": (
            max(s["peak_footprint_bytes"] for s in samples)
            + max(s["gateway"].get("heavy_worker", {}).get("max_completed_child_footprint_bytes", 0) for s in samples)
        )
        / 2**20,
        "pid": tail["pid"],
        "counts": document["counts"],
        "upstream_counts": tail["counts"],
        "topic_count": len(document["topics"]),
        "fault_cycles": len({r["cycle"] for r in document["transitions"] if r["mode"] == "all_offline"}),
        "active_samples": len(active),
        "active_history_samples": len(active_history),
        "history": tail["history"],
        "history_storage": tail["history_storage"],
        "history_completed": [c for c in checks if c["kind"] == "history_complete"],
        "peak_physical_mib": max(s["peak_footprint_bytes"] for s in samples) / 2**20,
        "sampled_peak_rss_mib": max(s["rss_bytes"] for s in samples) / 2**20,
        "final_physical_mib": tail["footprint_bytes"] / 2**20,
        "final_rss_mib": tail["rss_bytes"] / 2**20,
        "late_linear_slope_mib_per_minute": slope(late, "footprint_bytes"),
        "last_30m_linear_slope_mib_per_minute": slope(
            [row for row in active if row["elapsed_s"] >= active[-1]["elapsed_s"] - 1800], "footprint_bytes"
        ),
        "ten_minute_windows": buckets,
        "latencies_ms": {k: distribution(v) for k, v in latencies.items()},
        "http_statuses": {k: dict(v) for k, v in statuses.items()},
        "unexpected_http_errors": unexpected_http_errors,
        "incomplete_successful_bar_probes": incomplete_bar_successes,
        "source_timings_ms": tail["timings"],
        "timing_maxima_over_samples_ms": {
            name: max(s["timings"].get(name, {}).get("max_ms", 0) for s in samples)
            for name in {name for s in samples for name in s["timings"]}
        },
        "timing_retention_note": (
            "Per-sample percentiles retain the latest 4096 measurements per kind. "
            "Maxima over all recorded samples preserve earlier observed tails; "
            "they are not inferred from the final rolling window."
        ),
        "recovery_statuses": dict(Counter(c["status"] for c in recovered)),
        "offline_probe_statuses": dict(Counter(c["status"] for c in offline)),
        "client_errors": [c for c in checks if c["kind"] == "client_error"],
        "history_driver_errors": [c for c in checks if c["kind"] == "history_driver_error"],
        "driver_errors": [c for c in checks if c["kind"] in {"driver_error", "cleanup_error"}],
        "idle_seconds_observed": last_idle[-1]["elapsed_s"] - last_idle[0]["elapsed_s"] if last_idle else 0,
        "final_resources": {
            k: tail[k] for k in ("threads", "fds", "sockets", "async_tasks", "subscriptions", "gateway")
        },
        "method": document["method"],
        "limitations": [
            "Child-only fault injection; not a host network outage or multi-region measurement",
            "No forced GC or profiler during measurement; OS footprint includes native allocations",
            "History resume after exhausted retries is exercised by the test driver via production API",
            "One hour cannot establish multi-day leak absence; source availability is not guaranteed",
        ],
    }
    bar_topics = {name: row for name, row in document["topics"].items() if name.startswith("bars:")}
    result["bar_acquisition_freshness"] = {
        "topics": len(bar_topics),
        "distinct_acquisitions_per_topic": distribution(
            [row.get("distinct_acquisitions", 0) for row in bar_topics.values()]
        ),
        "maximum_gaps_seconds": distribution(
            [row["max_acquisition_gap_seconds"] for row in bar_topics.values() if "max_acquisition_gap_seconds" in row]
        ),
        "topics_with_gap_over_180s": sum(row.get("acquisition_gaps_over_180s", 0) > 0 for row in bar_topics.values()),
        "topics_never_acquired": [name for name, row in bar_topics.items() if not row.get("distinct_acquisitions")],
        "per_topic": bar_topics,
        "note": "Acquisition times, not exchange quote-update times. Includes injected outages; no replay claims.",
    }
    for prefix in ("bars:", "options:", "crypto:"):
        topics = {name: row for name, row in document["topics"].items() if name.startswith(prefix)}
        result.setdefault("acquisition_age_by_kind", {})[prefix[:-1]] = {
            "max_observed_age_seconds": distribution(
                [
                    row["max_observed_acquisition_age_seconds"]
                    for row in topics.values()
                    if "max_observed_acquisition_age_seconds" in row
                ]
            ),
            "minimum_acquisitions": min((row.get("distinct_acquisitions", 0) for row in topics.values()), default=0),
            "topics": topics,
        }
    routed = [row for row in checks if row["kind"] == "routed_history"]
    result["routed_history"] = {
        "jobs": len(routed),
        "states": dict(Counter(row["state"] for row in routed)),
        "successful_shapes": sorted(
            {
                ",".join(row["spec"]["codes"]) + ":" + row["spec"]["interval"]
                for row in routed
                if row["state"] in {"complete", "downloaded"} and row["rows"] > 0
            }
        ),
        "sources": sorted({source for row in routed for source in row.get("sources", [])}),
        "outcomes": routed,
    }
    scan_completed_at = next(
        (row["elapsed_s"] for row in samples if any(job.get("complete") for job in row["gateway"].get("scans", []))),
        None,
    )
    result["scan_completion_active_seconds"] = scan_completed_at - start if scan_completed_at is not None else None
    scan = document.get("scan_job") or {}
    if scan.get("total"):
        result["scan_completed_fraction"] = scan["completed"] / scan["total"]
        result["scan_unfinished_symbols"] = scan["total"] - scan["completed"]
    result["checks"] = {
        **({"full_scan_completed": bool(scan.get("complete"))} if scan else {}),
        "completed_one_hour_active": document["phase"] == "complete" and document["active_elapsed_s"] >= 3600,
        "same_server_process": result["same_pid"],
        "real_ws_and_history_work": tail["counts"].get("ws_live_events", 0) > 0
        and tail["counts"].get("history_success", 0) >= 610,
        "full_five_year_5m_job": any(
            c["spec"]["interval"] == "5m" and c["completed_chunks"] == 610 and c["rows"] > 0
            for c in result["history_completed"]
        ),
        "no_client_read_errors": not result["client_errors"],
        "no_unexpected_http_errors": not unexpected_http_errors,
        "no_incomplete_successful_bar_probes": not incomplete_bar_successes,
        "history_driver_survived": not result["history_driver_errors"],
        "driver_and_cleanup_survived": not result["driver_errors"],
        "all_recovery_probes_succeeded": bool(recovered) and all(c["status"] == 200 for c in recovered),
        "all_offline_probes_failed_visibly": bool(offline) and all(c["status"] == 503 for c in offline),
        "subscribers_and_topics_released": tail["subscriptions"]["clients"] == 0
        and not tail["subscriptions"]["topics"]
        and tail["subscriptions"]["pending_updates"] == 0,
        "websockets_released": tail["sockets"] == 0
        and tail["counts"].get("ws_connected", 0) == tail["counts"].get("ws_closed", 0),
        "source_requests_drained": tail["gateway"]["active_requests"] == 0,
        "history_worker_drained": all(h["state"] not in {"running", "queued"} for h in tail["history"]),
        "history_reservations_released": (tail.get("history_storage") or {}).get("reserved_bytes", 0) == 0,
        "idle_memory_cache_released": tail["gateway"]["cache"]["memory_bytes"] == 0,
        "sampled_cache_budgets_respected": all(
            s["gateway"]["cache"][kind] <= s["gateway"]["limits"][kind]
            for s in samples
            for kind in ("memory_bytes", "disk_bytes")
        ),
        "finished_scan_metadata_reclaimed": not tail["gateway"].get("scans"),
        "idle_observed_three_minutes": result["idle_seconds_observed"] >= 180,
    }
    if routed:
        result["checks"]["all_four_routed_history_shapes_acquired"] = (
            len(result["routed_history"]["successful_shapes"]) >= 4
        )
    timing = tail["timings"]
    started = timing.get("source_queue", {}).get("count", 0)
    finished = sum(timing.get(key, {}).get("count", 0) for key in ("source_success", "source_failed"))
    result["actual_source_calls_outstanding"] = started - finished
    result["checks"]["actual_source_calls_finished"] = started == finished
    if observer:
        rows = observer.get("samples", [])
        result["os_observer"] = {
            "pid": observer["pid"],
            "phase": observer["phase"],
            "error": observer.get("error"),
            "samples": len(rows),
            "observed_tree_peak_mib": max(r["tree_footprint_bytes"] for r in rows) / 2**20 if rows else None,
            "max_children": max(len(r["children"]) for r in rows) if rows else None,
            "distinct_child_pids": len({c["pid"] for r in rows for c in r["children"]}),
            "final_children": rows[-1]["children"] if rows else None,
            "final_tree_footprint_mib": rows[-1]["tree_footprint_bytes"] / 2**20 if rows else None,
        }
        result["checks"]["observer_same_pid_completed"] = (
            observer["pid"] == tail["pid"] and observer["phase"] == "complete" and not observer.get("error")
        )
        result["checks"]["children_released"] = bool(rows) and not rows[-1]["children"]
        result["checks"]["at_most_one_sdk_child"] = bool(rows) and max(len(r["children"]) for r in rows) <= 1
    # A footprint slope is evidence, not an automatic "no leak" assertion.
    return result


def plot(document, output, observer=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    samples = document["samples"]
    x = [s["elapsed_s"] / 60 for s in samples]
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    fig.patch.set_facecolor("#f6f3ed")
    for ax in axes:
        ax.set_facecolor("#f6f3ed")
        ax.grid(alpha=0.18)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].plot(
        x, [s["footprint_bytes"] / 2**20 for s in samples], label="Gateway parent physical footprint", color="#9c5f3d"
    )
    axes[0].plot(
        x, [s["rss_bytes"] / 2**20 for s in samples], label="Resident memory (RSS)", color="#607e79", alpha=0.8
    )
    axes[0].plot(
        x,
        [s["peak_footprint_bytes"] / 2**20 for s in samples],
        label="Parent OS lifetime physical peak",
        color="#b0a192",
        linestyle="--",
    )
    if observer and observer.get("samples"):
        origin = datetime.fromisoformat(document["started_utc"].replace("Z", "+00:00"))
        rows = observer["samples"]
        ox = [(datetime.fromisoformat(r["time"]) - origin).total_seconds() / 60 for r in rows]
        axes[0].plot(
            ox,
            [r["tree_footprint_bytes"] / 2**20 for r in rows],
            label="Parent + actual CCXT child (0.5s OS samples)",
            color="#363b45",
            linewidth=0.8,
            alpha=0.8,
        )
    axes[0].set_ylabel("MiB")
    axes[0].legend(loc="upper right", fontsize=9)
    axes[0].set_title("64 topics + whole-universe scan + multi-year history (fixed 8/64 MiB caches)")
    axes[1].plot(x, [s["threads"] for s in samples], label="Threads", color="#765c82")
    axes[1].plot(x, [s["fds"] for s in samples], label="Open file descriptors", color="#507c99")
    axes[1].plot(x, [s["sockets"] for s in samples], label="Upstream WebSockets", color="#71905d")
    axes[1].set_ylabel("Count")
    axes[1].legend(loc="upper right", fontsize=9)
    axes[2].plot(
        x,
        [s["counts"].get("history_success", 0) for s in samples],
        color="#9c5f3d",
        label="Successfully fetched real history chunks",
    )
    if document.get("scan_job"):
        scan_axis = axes[2].twinx()
        scan_progress, previous = [], 0
        for row in samples:
            jobs = row["gateway"].get("scans", [])
            if jobs:
                previous = sum(job["completed"] for job in jobs)
            scan_progress.append(previous)
        scan_axis.plot(x, scan_progress, color="#507c99", label="Scan symbols acquired", linewidth=1.4)
        universe_size = len((document.get("scale_universe") or {}).get("codes", []))
        scan_axis.set_ylabel(f"Scan symbols acquired (universe = {universe_size:,})")
        scan_axis.legend(loc="lower right", fontsize=8)
    axes[2].set_ylabel("Chunks")
    axes[2].set_xlabel("Wall-clock minutes (warmup + active load + idle tail)")
    axes[2].legend(loc="upper left", fontsize=9)
    for i, transition in enumerate(document["transitions"]):
        if transition["mode"] == "all_offline":
            end = (
                document["transitions"][i + 1]["elapsed_s"]
                if i + 1 < len(document["transitions"])
                else samples[-1]["elapsed_s"]
            )
            for ax in axes:
                ax.axvspan(transition["elapsed_s"] / 60, end / 60, color="#b85c4e", alpha=0.08)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plot", type=Path)
    parser.add_argument("--observer", type=Path)
    parser.add_argument("--partial", action="store_true")
    args = parser.parse_args()
    document = json.loads(args.input.read_text())
    if not args.partial and (document["phase"] != "complete" or document["active_elapsed_s"] < 3600):
        parser.error("Final report requires a completed >= 3600-second active workload")
    if any(row.get("footprint_bytes") is None for row in document["samples"]):
        parser.error("Physical-footprint analysis requires macOS samples; use gateway_soak_report.py for RSS-only runs")
    observer = json.loads(args.observer.read_text()) if args.observer else None
    result = summarize(document, observer)
    args.output.write_text(json.dumps(result, indent=2))
    if args.plot:
        plot(document, args.plot, observer)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "phase",
                    "active_elapsed_s",
                    "peak_physical_mib",
                    "final_physical_mib",
                    "late_linear_slope_mib_per_minute",
                )
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
