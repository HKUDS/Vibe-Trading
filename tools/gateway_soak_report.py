"""Summarize gateway soak process metrics without claiming a universal leak proof."""

import argparse
import json
from pathlib import Path
import statistics

MIB = 1024**2


def footprint(rows, aggregation):
    values = [row["footprint_bytes"] for row in rows if row["footprint_bytes"] is not None]
    return round(aggregation(values) / MIB, 3) if values else None


def difference(last, first):
    return round(last - first, 3) if last is not None and first is not None else None


def summarize(document):
    """Compare whole-process samples and repeated equivalent workload cycles."""
    samples = document["samples"]
    active = [row for row in samples if row["cycle"] >= 0 and row["phase"] != "idle"]
    final = samples[-1]
    cycles = {}
    for row in active:
        cycles.setdefault(row["cycle"], []).append(row)
    cycle_stats = []
    for cycle, rows in sorted(cycles.items()):
        cycle_stats.append(
            {
                "cycle": cycle + 1,
                "group": cycle % 4,
                "rss_median_mib": round(statistics.median(row["rss_bytes"] for row in rows) / MIB, 3),
                "footprint_median_mib": footprint(rows, statistics.median),
                "threads_max": max(row["threads"] for row in rows),
                "fds_max": max(row["fds"] for row in rows),
                "tasks_max": max(row["async_tasks"] for row in rows),
            }
        )
    comparisons = []
    for group in range(4):
        rows = [row for row in cycle_stats if row["group"] == group]
        if len(rows) > 1:
            comparisons.append(
                {
                    "group": group,
                    "first_cycle": rows[0]["cycle"],
                    "last_cycle": rows[-1]["cycle"],
                    "footprint_change_mib": difference(
                        rows[-1]["footprint_median_mib"], rows[0]["footprint_median_mib"]
                    ),
                    "rss_change_mib": round(rows[-1]["rss_median_mib"] - rows[0]["rss_median_mib"], 3),
                }
            )
    checks = document["checks"]
    offline = [row for row in checks if row["kind"] == "offline_bar_probe"]
    recovery = [row for row in checks if row["kind"] == "recovered_bar_probe"]
    return {
        "phase": document["phase"],
        "duration_minutes": round(document["elapsed_s"] / 60, 2),
        "sample_count": len(samples),
        "counts": document["counts"],
        "peak_rss_mib": round(max(row["rss_bytes"] for row in samples) / MIB, 3),
        "peak_footprint_mib": footprint(samples, max),
        "final_rss_mib": round(final["rss_bytes"] / MIB, 3),
        "final_footprint_mib": footprint([final], max),
        "cycle_stats": cycle_stats,
        "equivalent_workload_comparisons": comparisons,
        "final_resources": {
            key: final[key]
            for key in ("threads", "fds", "async_tasks", "sockets", "gateway", "subscriptions", "counts")
        },
        "max_pending_updates": max(row["subscriptions"]["pending_updates"] for row in samples),
        "offline_probes": {
            "total": len(offline),
            "refused": sum(row["status"] == 503 and not row["ok"] for row in offline),
        },
        "recovery_probes": {
            "total": len(recovery),
            "succeeded": sum(row["status"] == 200 and row["complete"] for row in recovery),
        },
        "topics_without_snapshot": [topic for topic, row in document["topics"].items() if not row["snapshots"]],
        "topics": document["topics"],
        "checks": checks,
        "scope": "Measured finite run with real public upstreams and transport-boundary fault injection. No forced GC. No claim about all sources, multi-day operation or the entire application.",
    }


def plot(document, destination):
    """Plot OS memory, threads/descriptors and cleanup on an elapsed-time axis."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    samples = document["samples"]
    x = [row["elapsed_s"] / 60 for row in samples]
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True, layout="constrained")
    fig.patch.set_facecolor("#faf8f3")
    for axis in axes:
        axis.set_facecolor("#faf8f3")
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="y", alpha=0.2)
    axes[0].plot(x, [row["rss_bytes"] / MIB for row in samples], label="Process RSS", color="#356d8b")
    if all(row["footprint_bytes"] is not None for row in samples):
        axes[0].plot(
            x, [row["footprint_bytes"] / MIB for row in samples], label="macOS physical footprint", color="#a26341"
        )
    axes[0].set_ylabel("MiB")
    axes[0].set_title("Gateway soak — whole-process memory and resource lifetime", loc="left")
    axes[0].legend(loc="upper left")
    axes[1].plot(x, [row["threads"] for row in samples], label="Threads", color="#356d8b")
    axes[1].plot(x, [row["fds"] for row in samples], label="File descriptors", color="#a26341")
    axes[1].plot(x, [row["async_tasks"] for row in samples], label="Async tasks", color="#6e7750")
    axes[1].set_ylabel("Count")
    axes[1].legend(loc="upper left", ncol=3)
    axes[2].plot(
        x,
        [row["gateway"]["cache"]["memory_bytes"] / MIB for row in samples],
        label="Serialized RAM cache",
        color="#356d8b",
    )
    axes[2].plot(
        x, [row["gateway"]["cache"]["disk_bytes"] / MIB for row in samples], label="Disk cache", color="#a26341"
    )
    axes[2].set_ylabel("MiB")
    axes[2].set_xlabel("Elapsed minutes · shaded: injected outages; gray: idle cleanup")
    axes[2].legend(loc="upper left")
    transitions = document["transitions"]
    for i, transition in enumerate(transitions):
        if transition["mode"] != "online":
            end = transitions[i + 1]["elapsed_s"] if i + 1 < len(transitions) else samples[-1]["elapsed_s"]
            for axis in axes:
                axis.axvspan(
                    transition["elapsed_s"] / 60,
                    end / 60,
                    color="#bb744e",
                    alpha=0.08 if transition["mode"] == "ws_offline" else 0.18,
                )
    idle = [row["elapsed_s"] / 60 for row in samples if row["phase"] == "idle"]
    if idle:
        for axis in axes:
            axis.axvspan(idle[0], x[-1], color="#777777", alpha=0.10)
    fig.savefig(destination, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--plot", type=Path)
    args = parser.parse_args()
    document = json.loads(args.report.read_text())
    print(json.dumps(summarize(document), indent=2))
    if args.plot:
        plot(document, args.plot)


if __name__ == "__main__":
    main()
