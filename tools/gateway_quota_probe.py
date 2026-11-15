"""Exercise default cache quotas with replayed real, verified history rows.

No new market observations are claimed: identical observed rows fill unique
storage keys to test eviction. Limits and the idle expiry are production defaults.
Prune is polled once per second; the housekeeping thread is tested separately.
"""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import time

from src.data_gateway.cache import Cache
from src.data_gateway.config import Config
from src.data_gateway.history_store import HistoryStore
from gateway_soak import process_memory


def run(args):
    store = HistoryStore(args.directory)
    try:
        rows = []
        offset = 0
        while offset is not None:
            page = store.read(args.job, offset, 1000)
            assert page["coverage_verified"]
            rows.extend(page["rows"])
            offset = page["next_offset"]
    finally:
        store.close()
    payload = {"ok": True, "data": rows}
    samples = []
    with tempfile.TemporaryDirectory(prefix="gateway-real-quota-") as directory:
        config = Config(Path(directory))
        cache = Cache(config)
        first = None
        newest = None
        for index in range(config.entries + 32):
            key = hashlib.sha256(str(index).encode()).hexdigest()
            first = first or key
            newest = key
            cache.put(key, payload)
            stats = cache.stats()
            assert stats["memory_bytes"] <= config.memory_bytes
            assert stats["disk_bytes"] <= config.disk_bytes
            assert stats["disk_entries"] <= config.entries
            if index % 32 == 0:
                samples.append({"written": index + 1, "cache": stats, **process_memory()})
        assert cache.get(first) is None and cache.get(newest)["payload"] == payload
        filled = cache.stats()
        assert filled["disk_entries"] < config.entries  # Bytes, not entry-count, forced eviction.
        fresh = Cache(config)
        assert fresh.get(newest)["payload"] == payload
        restarted = fresh.stats()
        del fresh
        started = time.monotonic()
        # Invoke the production prune method without touching any cache key.
        while time.monotonic() - started < config.memory_idle + config.cleanup_interval + 1:
            cache.prune()
            time.sleep(1)
        cache.prune()
        idle = cache.stats()
        assert idle["memory_bytes"] == 0 and idle["disk_bytes"] > 0
        report = {
            "complete": True,
            "real_rows": len(rows),
            "replayed_entries": config.entries + 32,
            "filled": filled,
            "new_cache_instance": restarted,
            "idle": idle,
            "idle_seconds": time.monotonic() - started,
            "samples": samples,
            "limits": {"memory": config.memory_bytes, "disk": config.disk_bytes, "entries": config.entries},
            "method": __doc__,
        }
        args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps({k: report[k] for k in ("complete", "real_rows", "filled", "idle", "idle_seconds")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
