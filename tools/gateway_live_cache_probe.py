"""Real-source cache refresh, process restart, and silent idle eviction probe.

Only timers are shortened; cache, response, worker and queue budgets use defaults.
The report contains metadata and digests, not market rows.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from src.data_gateway.config import Config
from src.data_gateway.service import MarketDataGateway


def run(cache, child=False):
    """Exercise a shared public option-chain request with bounded cache lifetimes."""
    config = replace(Config(cache), ttl=60 if child else 0.5, memory_idle=2, cleanup_interval=0.1)
    gateway = MarketDataGateway(config)
    calls = []
    original = gateway.invoke

    def invoke(*args, **kwargs):
        calls.append(time.monotonic())
        return original(*args, **kwargs)

    gateway.invoke = invoke

    def read():
        return gateway.options_chain("SPY", full=True)

    try:
        first = read()
        assert first["ok"] and first["data"]["calls"]
        if child:
            assert first["gateway"]["cache"] == "fresh" and not calls
            before = gateway.status()["cache"]
            until = time.monotonic() + 5
            while time.monotonic() < until and gateway.status()["cache"]["memory_entries"]:
                time.sleep(0.1)
            after = gateway.status()["cache"]
            assert before["memory_entries"] and after["memory_entries"] == 0 and after["disk_entries"]
            return {"disk_restart_hit": True, "source_calls": len(calls), "before": before, "after": after}
        assert len(calls) == 1
        time.sleep(0.6)
        started = time.monotonic()
        with ThreadPoolExecutor(10) as pool:
            results = list(pool.map(lambda _: read(), range(10)))
        elapsed = time.monotonic() - started
        assert all(value["ok"] for value in results)
        assert any(value["gateway"]["cache"] == "stale" for value in results)
        until = time.monotonic() + 20
        while time.monotonic() < until and gateway.status()["active_requests"]:
            time.sleep(0.1)
        assert len(calls) == 2 and not gateway.status()["active_requests"]
        return {
            "clients": 10,
            "source_calls_including_initial": len(calls),
            "burst_seconds": elapsed,
            "cache_states": [value["gateway"]["cache"] for value in results],
            "data_digest": hashlib.sha256(json.dumps(results[0]["data"], sort_keys=True).encode()).hexdigest(),
        }
    finally:
        gateway.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child-cache", type=Path)
    args = parser.parse_args()
    if args.child_cache:
        args.output.write_text(json.dumps(run(args.child_cache, True), indent=2))
        return
    with tempfile.TemporaryDirectory(prefix="gateway-live-cache-") as directory:
        parent = run(Path(directory))
        child_output = Path(directory) / "probe-child.json"
        subprocess.run(
            [sys.executable, __file__, "--output", str(child_output), "--child-cache", directory],
            check=True,
            timeout=30,
        )
        report = {
            "refresh": parent,
            "restart_and_idle": json.loads(child_output.read_text()),
            "timer_overrides_seconds": {"ttl": 0.5, "memory_idle": 2, "cleanup_interval": 0.1},
            "limits_unchanged": {"memory_mib": 8, "disk_mib": 64, "workers": 4, "pending": 16},
            "quota_eviction_in_this_probe": False,
        }
        args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report))


if __name__ == "__main__":
    main()
