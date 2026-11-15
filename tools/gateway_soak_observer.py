"""Independent macOS OS observer for the isolated gateway soak child."""

import argparse
import ctypes
from datetime import datetime, timezone
import json
from pathlib import Path
import time


class Usage(ctypes.Structure):
    _fields_ = [("uuid", ctypes.c_uint8 * 16), ("values", ctypes.c_uint64 * 35)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--max-seconds", type=float, default=14400)
    args = parser.parse_args()
    lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    samples = []
    child = None
    started = time.monotonic()
    error = None
    phase = None
    while time.monotonic() - started < args.max_seconds:
        try:
            report = json.loads(args.report.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(1)
            continue
        if not report["samples"]:
            time.sleep(1)
            continue
        pid = report["samples"][-1]["pid"]
        if child is not None and child != pid:
            raise RuntimeError("Measured process changed")
        child = pid
        phase = report["phase"]
        usage = Usage()
        if lib.proc_pid_rusage(child, 4, ctypes.byref(usage)) != 0:
            if phase != "complete":
                error = "Process disappeared before completed report"
            break
        child_pids = (ctypes.c_int * 16)()
        count = lib.proc_listchildpids(child, child_pids, ctypes.sizeof(child_pids))
        descendants = []
        for child_pid in list(child_pids)[: max(0, count)]:
            child_usage = Usage()
            if child_pid > 0 and lib.proc_pid_rusage(child_pid, 4, ctypes.byref(child_usage)) == 0:
                descendants.append(
                    {
                        "pid": child_pid,
                        "footprint_bytes": child_usage.values[7],
                        "peak_footprint_bytes": child_usage.values[28],
                        "rss_bytes": child_usage.values[6],
                    }
                )
        samples.append(
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "elapsed_s": round(time.monotonic() - started, 3),
                "phase": phase,
                "cycle": report["samples"][-1]["cycle"],
                "rss_bytes": usage.values[6],
                "footprint_bytes": usage.values[7],
                "peak_footprint_bytes": usage.values[28],
                "children": descendants,
                "tree_footprint_bytes": usage.values[7] + sum(p["footprint_bytes"] for p in descendants),
                "tree_rss_bytes": usage.values[6] + sum(p["rss_bytes"] for p in descendants),
                "cpu_seconds": (usage.values[0] + usage.values[1]) / 1e9,
            }
        )
        document = {"pid": child, "phase": phase, "error": error, "samples": samples}
        temporary = args.output.with_suffix(".tmp")
        if len(samples) % max(1, int(10 / args.interval)) == 0 or phase == "complete":
            temporary.write_text(json.dumps(document, indent=2))
            temporary.replace(args.output)
        if phase == "complete":
            break
        time.sleep(args.interval)
    args.output.write_text(json.dumps({"pid": child, "phase": phase, "error": error, "samples": samples}, indent=2))
    print(json.dumps({"pid": child, "phase": phase, "samples": len(samples), "error": error}), flush=True)


if __name__ == "__main__":
    main()
