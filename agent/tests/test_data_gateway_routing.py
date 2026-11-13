"""Region-independent recovery on observed network health, not assumed location."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pandas as pd

from src.data_gateway.config import Config
from src.data_gateway.service import MarketDataGateway
from src.data_gateway.routing import NetworkRouter
from src.data_gateway.streams import StreamHub, Topic


def test_prefer_local_success_then_reprobe_baseline_after_network_history_expires():
    now = [0]
    router = NetworkRouter(cooldown=10, lifetime=30, clock=lambda: now[0])
    router.record("options", "blocked_here", False, 5)
    router.record("options", "works_here", True, 0.1)
    assert router.order("options", ["blocked_here", "works_here"]) == ["works_here", "blocked_here"]
    assert router.cooling("options", "blocked_here")
    assert router.order("bars:hk", ["blocked_here", "works_here"]) == ["blocked_here", "works_here"]
    now[0] = 31
    assert router.order("options", ["blocked_here", "works_here"]) == ["blocked_here", "works_here"]
    assert not router.cooling("options", "blocked_here")


def test_existing_bar_loaders_switch_on_failure_without_changing_provenance(tmp_path, monkeypatch):
    from backtest.loaders import registry
    from src import market_data

    calls = []

    class Unavailable:
        name = "slow"
        volume_units = {}

        def is_available(self):
            return True

        def fetch(self, codes, *args, **kwargs):
            calls.append("slow")
            raise ConnectionError("upstream unavailable")

    class Fast:
        name = "fast"
        volume_units = {"us_equity": "shares"}

        def is_available(self):
            return True

        def fetch(self, codes, *args, **kwargs):
            calls.append("fast")
            return {codes[0]: pd.DataFrame({"close": [100.0]}, index=pd.to_datetime(["2026-01-01"]))}

    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "refresh_source_order_overrides", lambda: None)
    monkeypatch.setattr(registry, "LOADER_REGISTRY", {"slow": Unavailable, "fast": Fast})
    monkeypatch.setattr(registry, "FALLBACK_CHAINS", {"us_equity": ["slow", "fast"]})
    monkeypatch.setattr(market_data, "detect_source", lambda code: "slow")
    g = MarketDataGateway(Config(tmp_path))
    try:
        first = g.bars(codes=["AAPL.US"], start_date="2026-01-01", end_date="2026-01-02")
        assert first["ok"], first
        assert first["data"]["_provenance"]["AAPL.US"]["source"] == "fast"
        second = g.bars(codes=["MSFT.US"], start_date="2026-01-01", end_date="2026-01-02")
        assert second["ok"] and calls.count("slow") == 1
        assert second["data"]["_provenance"]["MSFT.US"]["volume_unit"] == "shares"
    finally:
        g.close()


def test_hybrid_continues_rest_when_socket_fails_and_stops_rest_when_socket_recovers(tmp_path):
    async def run():
        socket_ready = asyncio.Event()
        rest_calls = []

        async def socket(topic, publish):
            await socket_ready.wait()
            while True:
                publish("snapshot", {"ok": True, "data": {"source_time_ms": 20}, "gateway": {"transport": "websocket"}})
                await asyncio.sleep(0.01)

        async def rest(topic):
            rest_calls.append(1)
            return {"ok": True, "data": {"source_time_ms": 10}, "gateway": {"transport": "rest_poll"}}

        hub = StreamHub(
            SimpleNamespace(config=replace(Config(tmp_path), stream_snapshot_interval=0.05)),
            crypto_feed=socket,
            snapshot_feed=rest,
        )
        listener = hub.subscribe([Topic.parse("crypto:BTC-USDT")])
        assert (await asyncio.wait_for(listener.take(), 1))[0]["payload"]["gateway"]["transport"] == "rest_poll"
        await asyncio.sleep(0.07)
        assert len(rest_calls) >= 2
        socket_ready.set()
        await asyncio.sleep(0.03)
        count = len(rest_calls)
        await asyncio.sleep(0.13)
        assert len(rest_calls) == count
        assert (await listener.take())[0]["payload"]["gateway"]["transport"] == "websocket"
        await hub.close()
        assert not hub.channels

    asyncio.run(run())


def test_partial_crypto_history_is_not_reported_as_complete():
    from src.data_gateway.historical import describe_coverage

    params = {"start_date": "2026-11-11", "end_date": "2026-11-13", "interval": "1m"}
    result = describe_coverage([{"trade_date": "2026-11-12T18:00:00"}], params, "crypto")
    assert result["status"] == "partial"
    assert result["observed_start"] == "2026-11-12T18:00:00"
    # An exchange holiday is not evidence of a missing equity bar.
    assert describe_coverage([{"trade_date": "2026-11-12T18:00:00"}], params, "us_equity")["status"] == "unverified"


def test_gateway_partial_crypto_boundary_cannot_return_complete(tmp_path, monkeypatch):
    import json
    from backtest.loaders import registry
    from src import market_data

    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "refresh_source_order_overrides", lambda: None)
    monkeypatch.setattr(market_data, "detect_source", lambda code: "okx")
    monkeypatch.setattr(
        market_data,
        "fetch_market_data_json",
        lambda **kwargs: json.dumps(
            {
                "BTC-USDT": [{"trade_date": "2026-11-12T18:00:00", "close": 100}],
                "_provenance": {"BTC-USDT": {"source": "okx"}},
            }
        ),
    )
    gateway = MarketDataGateway(Config(tmp_path))
    try:
        result = gateway.bars(codes=["BTC-USDT"], start_date="2026-11-11", end_date="2026-11-13", interval="1m")
        assert result["ok"]
        assert result["complete"] is False
        assert result["data"]["_coverage"]["BTC-USDT"]["status"] == "partial"
    finally:
        gateway.close()
