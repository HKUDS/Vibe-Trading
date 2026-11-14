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


def test_half_open_probe_keeps_outage_throttle_but_recovers_before_exponential_expiry():
    now = [0]
    router = NetworkRouter(cooldown=30, lifetime=300, clock=lambda: now[0])
    router.record("bars:crypto:1D", "okx", False, 1)
    router.record("bars:crypto:1D", "okx", False, 1)
    assert router.recovery_probe("bars:crypto:1D", ["okx"]) is None
    now[0] = 31
    assert router.cooling("bars:crypto:1D", "okx")  # Original 60-second backoff.
    assert router.recovery_probe("bars:crypto:1D", ["okx"]) == "okx"
    assert all(router.recovery_probe("bars:crypto:1D", ["okx"]) is None for _ in range(100))
    router.record("bars:crypto:1D", "okx", True, 0.1)
    assert not router.cooling("bars:crypto:1D", "okx")
    assert router.recovery_probe("bars:us:1D", ["okx"]) is None


def test_recovered_source_is_actually_called_while_old_cooldown_would_return_503(tmp_path, monkeypatch):
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backtest.loaders import registry
    from src import market_data
    from src.data_gateway import api

    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "refresh_source_order_overrides", lambda: None)
    monkeypatch.setattr(registry, "FALLBACK_CHAINS", {"crypto": ["okx"]})
    monkeypatch.setattr(market_data, "detect_source", lambda code: "okx")
    calls = []

    def fetch(**kwargs):
        calls.append(1)
        return json.dumps(
            {"BTC-USDT": [{"trade_date": "2026-11-01", "close": 100}], "_provenance": {"BTC-USDT": {"source": "okx"}}}
        )

    monkeypatch.setattr(market_data, "fetch_market_data_json", fetch)
    gateway = MarketDataGateway(Config(tmp_path))
    now = [0]
    gateway.router.clock = lambda: now[0]
    for _ in range(2):
        gateway.router.record("bars:crypto:1D", "okx", False, 1)
    monkeypatch.setattr(api, "get_gateway", lambda: gateway)
    app = FastAPI()
    api.register_gateway_routes(app, lambda: None)
    try:
        with TestClient(app) as client:
            params = {"codes": ["BTC-USDT"], "start_date": "2026-11-01", "end_date": "2026-11-02", "interval": "1D"}
            response = client.post("/data/bars", json=params)
            assert response.status_code == 503 and calls == []
            # A distinct page avoids the deliberate per-request 30s throttle.
            now[0] = 31
            response = client.post("/data/bars", json={**params, "max_rows": 99})
            assert response.status_code == 200, response.text
            assert response.json()["ok"] and len(calls) == 1
    finally:
        gateway.close()


def test_recovery_prefers_previously_working_source_and_rotates_if_it_still_fails():
    now = [0.0]
    router = NetworkRouter(cooldown=30, lifetime=300, clock=lambda: now[0])
    scope = "bars:a_share:1D"
    router.record(scope, "working", True, 1)
    for _ in range(4):
        router.record(scope, "working", False, 1)
    for _ in range(3):
        router.record(scope, "blocked", False, 1)
        router.record(scope, "alternative", False, 1)
    now[0] = 31
    assert router.recovery_probe(scope, ["blocked", "working", "alternative"]) == "working"
    assert all(router.recovery_probe(scope, ["blocked", "working", "alternative"]) is None for _ in range(100))
    router.record(scope, "working", False, 1)
    now[0] = 62
    assert router.recovery_probe(scope, ["blocked", "working", "alternative"]) == "blocked"
    router.record(scope, "blocked", False, 1)
    now[0] = 93
    assert router.recovery_probe(scope, ["blocked", "working", "alternative"]) == "alternative"
    router.record(scope, "working", True, 1)
    assert scope not in router.probe_tried
    assert not router.cooling(scope, "working")
    now[0] = 500
    router.prune()
    assert not router.health and not router.probe_tried


def test_options_recover_while_exponential_cooldown_is_still_active(tmp_path):
    from src.data_gateway.config import Config
    from src.data_gateway.service import MarketDataGateway
    from dataclasses import replace
    import time

    calls = []
    gateway = MarketDataGateway(
        replace(Config(tmp_path), sources=("test",)),
        {
            "options_chain": {
                "test": lambda **kwargs: calls.append(1) or {"ok": True, "data": {"ticker": kwargs["ticker"]}}
            }
        },
    )
    now = [0.0]
    gateway.router.clock = lambda: now[0]
    gateway.router.record("options_chain", "test", True, 1)
    for _ in range(4):
        gateway.router.record("options_chain", "test", False, 1)
    gateway.failures[("options_chain", "test")] = time.monotonic() + 100
    try:
        assert not gateway.options_chain("AAPL")["ok"] and not calls
        now[0] = 31
        recovered = gateway.options_chain("SPY")
        assert recovered["ok"] and calls == [1]
        assert not gateway.router.cooling("options_chain", "test")
        assert ("options_chain", "test") not in gateway.failures
    finally:
        gateway.close()


def test_options_capacity_pressure_has_short_retry_without_poisoning_health(tmp_path):
    from src.data_gateway.config import Config
    from src.data_gateway.service import MarketDataGateway
    from dataclasses import replace

    calls = []
    gateway = MarketDataGateway(
        replace(Config(tmp_path), sources=("test",)),
        {"options_chain": {"test": lambda **kwargs: calls.append(1) or {"ok": True}}},
    )
    try:
        for _ in range(gateway.config.workers):
            assert gateway.source_slots.acquire(blocking=False)
        value = gateway.options_chain("AAPL")
        assert not value["ok"] and value["retry_after_seconds"] == 1 and not calls
        assert not gateway.router.health and not gateway.failures
        for _ in range(gateway.config.workers):
            gateway.source_slots.release()
        assert gateway.options_chain("SPY")["ok"] and calls == [1]
    finally:
        gateway.close()


def test_binance_inherited_sdk_uses_isolation_before_availability(tmp_path, monkeypatch):
    from backtest.loaders import registry
    from backtest.loaders.binance_loader import DataLoader as Binance
    from backtest.loaders.ccxt_loader import DataLoader as Ccxt
    from src.data_gateway import isolated

    registry._ensure_registered()
    calls = []

    def forbidden(self):
        raise AssertionError("Heavy SDK availability imported in the parent")

    def child(params, timeout, limit):
        calls.append(params["source"])
        assert 0 < timeout <= 6
        assert limit == 2 * 1024**2
        return {
            "BTC-USDT": [{"trade_date": "2026-11-12", "close": 100}],
            "_provenance": {"BTC-USDT": {"source": params["source"], "quote_currency": "USDT"}},
        }

    monkeypatch.setattr(Ccxt, "is_available", forbidden)
    monkeypatch.setattr(isolated, "fetch", child)
    gateway = MarketDataGateway(Config(tmp_path))
    try:
        for source in ("binance", "ccxt"):
            result = gateway.bars(
                source=source,
                codes=["BTC-USDT"],
                start_date="2026-11-12",
                end_date="2026-11-12",
                interval="1D",
            )
            assert result["ok"], result
            assert result["data"]["_provenance"]["BTC-USDT"]["source"] == source
        assert calls == ["binance", "ccxt"]
        assert isolated.requires_isolation(Binance)
    finally:
        gateway.close()


def test_skipped_options_routes_do_not_restart_a_full_request_cooldown(tmp_path, monkeypatch):
    """A new symbol just before half-open must recover at the source deadline."""
    import threading
    import time
    from src.data_gateway import service

    now = [100.0]
    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: now[0], time=time.time))
    calls = []
    gateway = MarketDataGateway(
        replace(Config(tmp_path), sources=("test",)),
        {"options_chain": {"test": lambda **kwargs: calls.append(kwargs["ticker"]) or {"ok": True}}},
    )
    gateway.router.clock = lambda: now[0]
    finished = threading.Event()
    original_done = gateway._done

    def done(key, future):
        original_done(key, future)
        finished.set()

    monkeypatch.setattr(gateway, "_done", done)
    for _ in range(4):
        gateway.router.record("options_chain", "test", False, 0.1)
    gateway.failures[("options_chain", "test")] = now[0] + 30
    try:
        now[0] = 129.0
        first = gateway.options_chain("AAPL", allow_stale=False)
        assert finished.wait(1)
        assert not first["ok"] and calls == []
        assert 0 < first["retry_after_seconds"] <= 1.01
        # Repeated callers still cannot probe ahead of the original deadline.
        assert not gateway.options_chain("AAPL", allow_stale=False)["ok"]
        assert calls == []
        now[0] = 130.1
        assert gateway.options_chain("AAPL", allow_stale=False)["ok"]
        assert calls == ["AAPL"]
    finally:
        gateway.close()


def test_router_retry_delay_keeps_exponential_and_half_open_limits():
    now = [100.0]
    router = NetworkRouter(clock=lambda: now[0])
    for _ in range(4):
        router.record("options", "a", False, 1)
    now[0] = 129
    assert router.retry_after("options", ["a"]) == 1
    assert router.recovery_probe("options", ["a"]) is None
    now[0] = 130
    assert router.recovery_probe("options", ["a"]) == "a"
    assert router.retry_after("options", ["a"]) == 30
    assert router.recovery_probe("options", ["a"]) is None
    # A healthy alternative must not inherit a failed source's delay.
    router.record("options", "b", True, 0.1)
    assert router.retry_after("options", ["a", "b"]) == 0
