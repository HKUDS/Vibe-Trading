"""Summarize finished live gateway soak evidence without retaining market data."""

import argparse
from collections import Counter, defaultdict
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


def summarize(document):
    samples, checks = document["samples"], document["checks"]
    active = [s for s in samples if s["cycle"] >= 0 and s["phase"] != "idle"]
    start = active[0]["elapsed_s"]
    late = [s for s in active if s["elapsed_s"] - start >= 30 * 60]
    buckets = []
    for minute in range(0, 70, 10):
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
        statuses[kind][str(status)] += 1
        cache = (row.get("gateway") or {}).get("cache", "none")
        latencies[f"{kind}:http{status}:cache={cache}"].append(row["latency_ms"])
    tail = samples[-1]
    last_idle = [s for s in samples if s["phase"] == "idle"]
    recovered = [c for c in checks if c["kind"] == "recovered_bar_probe"]
    offline = [c for c in checks if c["kind"] == "offline_bar_probe"]
    active_history = [s for s in active if any(h["state"] in {"running", "queued", "failed"} for h in s["history"])]
    result = {
        "phase": document["phase"],
        "started_utc": document["started_utc"],
        "elapsed_s": document["elapsed_s"],
        "active_elapsed_s": document["active_elapsed_s"],
        "same_pid": len({s["pid"] for s in samples}) == 1,
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
        "ten_minute_windows": buckets,
        "latencies_ms": {k: distribution(v) for k, v in latencies.items()},
        "http_statuses": {k: dict(v) for k, v in statuses.items()},
        "source_timings_ms": tail["timings"],
        "recovery_statuses": dict(Counter(c["status"] for c in recovered)),
        "offline_probe_statuses": dict(Counter(c["status"] for c in offline)),
        "client_errors": [c for c in checks if c["kind"] == "client_error"],
        "history_driver_errors": [c for c in checks if c["kind"] == "history_driver_error"],
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
    result["checks"] = {
        "completed_one_hour_active": document["phase"] == "complete" and document["active_elapsed_s"] >= 3600,
        "same_server_process": result["same_pid"],
        "real_ws_and_history_work": tail["counts"].get("ws_live_events", 0) > 0
        and tail["counts"].get("history_success", 0) >= 610,
        "full_five_year_5m_job": any(
            c["spec"]["interval"] == "5m" and c["completed_chunks"] == 610 and c["rows"] > 0
            for c in result["history_completed"]
        ),
        "no_client_read_errors": not result["client_errors"],
        "history_driver_survived": not result["history_driver_errors"],
        "all_recovery_probes_succeeded": bool(recovered) and all(c["status"] == 200 for c in recovered),
        "all_offline_probes_failed_visibly": bool(offline) and all(c["status"] == 503 for c in offline),
        "subscribers_and_topics_released": tail["subscriptions"]["clients"] == 0
        and not tail["subscriptions"]["topics"]
        and tail["subscriptions"]["pending_updates"] == 0,
        "websockets_released": tail["sockets"] == 0
        and tail["counts"].get("ws_connected", 0) == tail["counts"].get("ws_closed", 0),
        "source_requests_drained": tail["gateway"]["active_requests"] == 0,
        "history_worker_drained": all(h["state"] not in {"running", "queued"} for h in tail["history"]),
        "idle_observed_three_minutes": result["idle_seconds_observed"] >= 180,
    }
    # A footprint slope is evidence, not an automatic "no leak" assertion.
    return result


def plot(document, output):
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
        x, [s["footprint_bytes"] / 2**20 for s in samples], label="Whole-process physical footprint", color="#9c5f3d"
    )
    axes[0].plot(
        x, [s["rss_bytes"] / 2**20 for s in samples], label="Resident memory (RSS)", color="#607e79", alpha=0.8
    )
    axes[0].plot(
        x,
        [s["peak_footprint_bytes"] / 2**20 for s in samples],
        label="OS lifetime physical peak",
        color="#b0a192",
        linestyle="--",
    )
    axes[0].set_ylabel("MiB")
    axes[0].legend(loc="upper right", fontsize=9)
    axes[0].set_title("One process: live subscriptions + multi-year history downloads")
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
    parser.add_argument("--partial", action="store_true")
    args = parser.parse_args()
    document = json.loads(args.input.read_text())
    if not args.partial and (document["phase"] != "complete" or document["active_elapsed_s"] < 3600):
        parser.error("Final report requires a completed >= 3600-second active workload")
    if any(row.get("footprint_bytes") is None for row in document["samples"]):
        parser.error("Physical-footprint analysis requires macOS samples; use gateway_soak_report.py for RSS-only runs")
    result = summarize(document)
    args.output.write_text(json.dumps(result, indent=2))
    if args.plot:
        plot(document, args.plot)
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
