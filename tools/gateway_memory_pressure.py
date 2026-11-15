"""Synthetic near-entry-limit churn against the real gateway cache and StreamHub.

Complements live small-payload soak; synthetic data is never financial evidence.
No forced GC. Uses a temporary cache and normal production resource limits.
"""

import asyncio
import json
from pathlib import Path
import tempfile
import time

from gateway_capacity_probe import memory
from src.data_gateway.config import Config
from src.data_gateway.service import MarketDataGateway
from src.data_gateway.streams import StreamHub, Topic


async def main():
    samples = []
    count = 0

    def provider(**params):
        nonlocal count
        count += 1
        # A distinct large string each acquisition, below the 2 MiB entry cap.
        return {"ok": True, "source": "synthetic", "data": {"blob": str(count) + "x" * 1800000}}

    with tempfile.TemporaryDirectory(prefix="gateway-pressure-") as directory:
        gateway = MarketDataGateway(
            Config(Path(directory), sources=("synthetic",)), {"options_chain": {"synthetic": provider}}
        )
        hub = StreamHub(gateway)
        try:
            for cycle in range(20):
                topics = [Topic.parse(f"options:LOAD{cycle}X{i}") for i in range(16)]
                first = hub.subscribe(topics[:8])
                second = hub.subscribe(topics[8:])
                # Deliberately never consume updates; only latest state retained.
                deadline = time.monotonic() + 20
                while (len(first.pending) + len(second.pending) < 16) and time.monotonic() < deadline:
                    await asyncio.sleep(0.05)
                assert len(first.pending) + len(second.pending) == 16
                assert all(
                    value["event"] == "snapshot" and value["payload"]["ok"]
                    for listener in (first, second)
                    for value in listener.pending.values()
                )
                await hub.unsubscribe(first)
                await hub.unsubscribe(second)
                samples.append(
                    {"cycle": cycle + 1, **memory(), "cache": gateway.cache.stats(), "subscriptions": hub.status()}
                )
                assert not hub.channels and not hub.listeners
                assert gateway.cache.memory_size <= gateway.config.memory_bytes
                assert gateway.cache.stats()["disk_bytes"] <= gateway.config.disk_bytes
                print(
                    json.dumps({"cycle": cycle + 1, "footprint_mib": samples[-1].get("footprint_bytes", 0) / 2**20}),
                    flush=True,
                )
            await hub.close()
        finally:
            gateway.close()
    Path("/tmp/vibe-gateway-pressure-20261114.json").write_text(
        json.dumps(
            {
                "synthetic": True,
                "payload_bytes_approx": 1800000,
                "acquisitions": count,
                "samples": samples,
                "temporary_data_removed": not Path(directory).exists(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
