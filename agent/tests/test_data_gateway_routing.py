"""Region-independent recovery on observed network health, not assumed location."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest

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

    def done(key, future, **kwargs):
        original_done(key, future, **kwargs)
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


def test_later_same_adapter_success_allows_one_probe_without_clearing_backoff():
    now = [100.0]
    router = NetworkRouter(cooldown=30, clock=lambda: now[0])
    router.record("bars:a_share:1D", "yahoo", False, 1)
    # Different adapters and success before this failure prove nothing.
    router.record("bars:us_equity:1D", "yahoo", True, 0.1)
    now[0] += 1
    router.record("bars:crypto:1D", "okx", True, 0.1)
    assert router.recovery_probe("bars:a_share:1D", ["yahoo"]) is None
    router.record("bars:us_equity:1D", "yahoo", True, 0.1)
    assert router.retry_after("bars:a_share:1D", ["yahoo"]) == 0
    assert router.recovery_probe("bars:a_share:1D", ["yahoo"]) == "yahoo"
    assert router.cooling("bars:a_share:1D", "yahoo")
    assert all(router.recovery_probe("bars:a_share:1D", ["yahoo"]) is None for _ in range(100))
    router.record("bars:a_share:1D", "yahoo", False, 0.1)
    now[0] += 1
    router.record("bars:us_equity:1D", "yahoo", True, 0.1)
    assert router.recovery_probe("bars:a_share:1D", ["yahoo"]) is None
    assert router.retry_after("bars:a_share:1D", ["yahoo"]) == 29


@pytest.mark.parametrize("restored", [True, False])
def test_mixed_request_completes_only_cooled_missing_market_after_sibling_success(tmp_path, monkeypatch, restored):
    import time
    from backtest.loaders import registry
    from src import market_data

    registry._ensure_registered()
    calls = []

    class Loader:
        name = "recovery_fixture"
        volume_units = {"us_equity": "shares", "a_share": "shares"}

        def is_available(self):
            return True

        def fetch(self, codes, *args, **kwargs):
            calls.extend(codes)
            if "601398.SH" in codes and not restored:
                raise ConnectionError("A-share endpoint still unavailable")
            time.sleep(0.02)  # A-share walker first finishes while this call runs.
            result = {}
            for code in codes:
                frame = pd.DataFrame(
                    {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.0], "volume": [100.0]},
                    index=pd.to_datetime(["2026-11-12"]),
                )
                frame.index.name = "trade_date"
                frame.attrs["quote_currency"] = "CNY" if code.endswith(".SH") else "USD"
                result[code] = frame
            return result

    monkeypatch.setitem(registry.LOADER_REGISTRY, Loader.name, Loader)
    for market in ("a_share", "us_equity"):
        monkeypatch.setitem(registry.FALLBACK_CHAINS, market, [Loader.name])
    monkeypatch.setattr(registry, "get_source_order_override", lambda market: None)
    monkeypatch.setattr(market_data, "detect_source", lambda code: Loader.name)
    gateway = MarketDataGateway(Config(tmp_path))
    try:
        gateway.router.record("bars:a_share:1D", Loader.name, False, 0.1)
        response = gateway.bars(
            codes=["601398.SH", "AAPL.US"], start_date="2026-11-12", end_date="2026-11-12", interval="1D"
        )
        assert calls == ["AAPL.US", "601398.SH"]  # Healthy data is never replayed.
        if not restored:
            assert response["complete"] is False
            assert response["data"]["_unresolved"] == ["601398.SH"]
            assert gateway.router.cooling("bars:a_share:1D", Loader.name)
            assert gateway.router.recovery_probe("bars:a_share:1D", [Loader.name]) is None
            assert gateway.cache.stats()["memory_entries"] == 0
            assert response["data"]["_diagnostics"]["601398.SH"][-1]["reason"] == "network_failure"
            return
        assert response["complete"] is True, response
        assert response["data"]["_recovery"]["601398.SH"]["state"] == "recovered_in_request"
        assert "retry_after_seconds" not in response
        assert response["data"]["_provenance"]["601398.SH"]["quote_currency"] == "CNY"
        assert response["data"]["_provenance"]["AAPL.US"]["quote_currency"] == "USD"
        assert response["data"]["_diagnostics"]["601398.SH"][0]["reason"] == "network_cooldown"
    finally:
        gateway.close()


def test_cooldown_partial_exposes_actual_remaining_delay_and_is_not_cached(tmp_path, monkeypatch):
    from backtest.loaders import registry
    from src import market_data

    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "get_source_order_override", lambda market: None)
    monkeypatch.setattr(registry, "FALLBACK_CHAINS", {"a_share": ["blocked"]})
    monkeypatch.setattr(market_data, "detect_source", lambda code: "blocked")
    gateway = MarketDataGateway(Config(tmp_path))
    now = [100.0]
    gateway.router.clock = lambda: now[0]
    try:
        gateway.router.record("bars:a_share:1D", "blocked", False, 1)
        now[0] += 25
        value = gateway.bars(codes=["601398.SH"], start_date="2026-11-12", end_date="2026-11-12", interval="1D")
        assert not value["complete"]
        assert value["retry_after_seconds"] == 5
        assert value["data"]["_recovery"]["601398.SH"] == {"state": "waiting_for_route", "retry_after_seconds": 5}
        assert gateway.cache.stats()["memory_entries"] == 0
    finally:
        gateway.close()


def test_known_healthy_fallback_precedes_unobserved_baseline():
    router = NetworkRouter()
    router.record("bars:a_share:1D", "yahoo", True, 0.1)
    assert router.order("bars:a_share:1D", ["tencent", "yahoo"]) == ["yahoo", "tencent"]
    assert router.order("bars:hk_equity:1D", ["tencent", "yahoo"]) == ["tencent", "yahoo"]


@pytest.mark.parametrize('escape', ['cooled', 'unconfigured', 'broken', 'healthy', 'fails'])
def test_sdk_waits_when_declared_fallbacks_are_not_available(tmp_path, monkeypatch, escape):
    """A busy sole healthy source waits once; a real alternative still bypasses it."""
    import threading
    from backtest.loaders import registry, baostock_loader
    from backtest.loaders.acquisition import source_can_fallback
    from src import market_data

    calls = []
    sdk_network_reads = []
    holding, release = threading.Event(), threading.Event()

    def hold():
        with baostock_loader._session_admission(2) as acquired:
            assert acquired
            holding.set()
            release.wait(2)

    thread = threading.Thread(target=hold)
    thread.start()
    assert holding.wait(1)

    class SDK:
        name = 'sdk'
        volume_units = {'us_equity': 'shares'}

        def is_available(self):
            return True

        def fetch(self, codes, *args, **kwargs):
            calls.append(('sdk', source_can_fallback.get()))
            with baostock_loader._session_admission(1) as admitted:
                if not admitted:
                    self.fetch_errors = {c: 'source_busy' for c in codes}
                    return {}
                sdk_network_reads.append(tuple(codes))
                return {c: pd.DataFrame({'close': [100.]}, index=pd.to_datetime(['2026-01-02'])) for c in codes}

    class Alternative(SDK):
        name = 'alternative'

        def __init__(self):
            if escape == 'broken':
                raise RuntimeError('Optional SDK lacks credentials')

        def is_available(self):
            return escape != 'unconfigured'

        def fetch(self, codes, *args, **kwargs):
            calls.append(('alternative', source_can_fallback.get()))
            if escape == 'fails':
                raise ConnectionError('Alternative failed before usable data')
            return {c: pd.DataFrame({'close': [101.]}, index=pd.to_datetime(['2026-01-02'])) for c in codes}

    monkeypatch.setattr(registry, '_ensure_registered', lambda: None)
    monkeypatch.setattr(registry, 'refresh_source_order_overrides', lambda: None)
    monkeypatch.setattr(registry, 'LOADER_REGISTRY', {'sdk': SDK, 'alternative': Alternative})
    monkeypatch.setattr(registry, 'FALLBACK_CHAINS', {'us_equity': ['sdk', 'alternative']})
    monkeypatch.setattr(market_data, 'detect_source', lambda code: 'sdk')
    gateway = MarketDataGateway(Config(tmp_path))
    if escape == 'cooled':
        gateway.router.record('bars:us_equity:1D', 'alternative', False, .01)
    timer = threading.Timer(.15, release.set)
    timer.start()
    try:
        value = gateway.bars(codes=['AAPL.US'], start_date='2026-01-02', end_date='2026-01-02')
        assert value['ok'], value
        assert len(sdk_network_reads) == (0 if escape == 'healthy' else 1)
        assert calls[0] == ('sdk', escape in {'healthy', 'fails'})
        assert [c[0] for c in calls] == (['sdk', 'alternative', 'sdk'] if escape == 'fails' else ['sdk', 'alternative'] if escape == 'healthy' else ['sdk'])
        if escape == 'fails':
            assert calls[-1] == ('sdk', False)
            assert not gateway.router.cooling('bars:us_equity:1D', 'sdk')
        assert value['data']['_provenance']['AAPL.US']['source'] == ('alternative' if escape == 'healthy' else 'sdk')
    finally:
        release.set()
        timer.join()
        thread.join()
        gateway.close()


@pytest.mark.parametrize('reasons', [['source_busy'], ['source_busy', 'network_failure']])
def test_failed_network_attempt_is_never_reissued_as_deferred_admission(tmp_path, monkeypatch, reasons):
    """Only wholly local admission failures qualify; mixed/network failures do not."""
    import json
    from backtest.loaders import registry
    from src import market_data

    calls = []
    monkeypatch.setattr(registry, '_ensure_registered', lambda: None)
    monkeypatch.setattr(registry, 'get_source_order_override', lambda market: None)
    monkeypatch.setattr(registry, 'LOADER_REGISTRY', {
        source: lambda: SimpleNamespace(is_available=lambda: True) for source in ('first', 'second')
    })
    monkeypatch.setattr(registry, 'FALLBACK_CHAINS', {'us_equity': ['first', 'second']})
    monkeypatch.setattr(market_data, 'detect_source', lambda code: 'first')

    def fetch(**params):
        calls.append(params['source'])
        return json.dumps({'_diagnostics': {c: {'attempts': [
            {'reason': reason} for reason in reasons
        ]} for c in params['codes']}})

    monkeypatch.setattr(market_data, 'fetch_market_data_json', fetch)
    gateway = MarketDataGateway(Config(tmp_path))
    try:
        value = gateway.bars(codes=['AAPL.US'], start_date='2026-01-02', end_date='2026-01-02')
        assert not value['ok']
        assert calls == ['first', 'second']
    finally:
        gateway.close()
