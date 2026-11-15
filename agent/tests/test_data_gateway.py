"""Gateway recovery/resource tests; synthetic providers, no public network."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import os
import threading
import time

import pytest

from src.data_gateway.cache import Cache
from src.data_gateway.config import Config
from src.data_gateway.service import MarketDataGateway, GatewayError
from src.data_gateway.sources import normalize


@pytest.fixture
def gateways(tmp_path):
    instances = []

    def build(providers, **limits):
        config = replace(Config(cache_dir=tmp_path / str(len(instances)), sources=tuple(providers)), **limits)
        gateway = MarketDataGateway(config, {"options_chain": providers})
        instances.append(gateway)
        return gateway

    yield build
    for gateway in instances:
        gateway.close()


def data(**kwargs):
    return {"ok": True, "source": "test", "data": {"ticker": kwargs.get("ticker", "AAPL"), "calls": [1]}}


def test_failure_switches_provider_and_cools_down_only_failed_source(gateways):
    calls = []

    def failed(**kwargs):
        calls.append("failed")
        raise ConnectionError("upstream offline")

    g = gateways({"bad": failed, "good": data})
    r = g.options_chain("AAPL")
    assert r["ok"] and r["gateway"]["attempts"] == [
        {"source": "bad", "status": "unavailable"},
        {"source": "good", "status": "ok"},
    ]
    assert g.options_chain("TSLA")["gateway"]["attempts"] == [{"source": "good", "status": "ok"}]
    assert g.router.cooling("options_chain", "bad")
    assert calls == ["failed"]


def test_identical_requests_share_one_fetch_and_cached_results_are_unshared(gateways):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def provider(**kwargs):
        calls.append(1)
        entered.set()
        release.wait(2)
        return data(**kwargs)

    g = gateways({"test": provider})
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(g.options_chain, "AAPL.US") for _ in range(12)]
        assert entered.wait(1)
        time.sleep(0.02)
        release.set()
        results = [f.result() for f in futures]
    assert len(calls) == 1
    results[0]["data"]["calls"].append("mutation")
    assert g.options_chain("AAPL")["data"]["calls"] == [1]
    assert g.options_chain("AAPL")["gateway"]["cache"] == "fresh"


def test_stale_snapshot_returns_immediately_while_one_refresh_runs(gateways):
    release, entered = threading.Event(), threading.Event()
    calls = []

    def provider(**kwargs):
        calls.append(1)
        if len(calls) > 1:
            entered.set()
            release.wait(2)
        return data(**kwargs)

    g = gateways({"test": provider}, ttl=0.02, stale_ttl=10)
    assert g.options_chain("AAPL")["ok"]
    time.sleep(0.03)
    start = time.monotonic()
    r = g.options_chain("AAPL")
    assert time.monotonic() - start < 0.1
    assert r["gateway"]["cache"] == "stale"
    assert entered.wait(1)
    for _ in range(10):
        assert g.options_chain("AAPL")["gateway"]["cache"] == "stale"
    release.set()
    assert len(calls) == 2


def test_timeout_retains_worker_capacity_and_never_spawns_replacements(gateways):
    release = threading.Event()

    def stuck(**kwargs):
        release.wait(2)
        return data(**kwargs)

    g = gateways({"stuck": stuck, "healthy": data}, workers=1, source_timeout=0.02, request_timeout=0.2)
    start = time.monotonic()
    result = g.options_chain("AAPL")
    assert not result["ok"] and time.monotonic() - start < 0.3
    assert result["gateway"]["attempts"][-1]["status"] == "busy"
    assert not g.source_slots.acquire(blocking=False)
    release.set()


def test_cold_disk_cache_survives_restart_and_cleanup_reclaims_memory_and_files(tmp_path):
    config = Config(cache_dir=tmp_path, memory_bytes=500, disk_bytes=600, entry_bytes=400, entries=2, stale_ttl=10)
    c = Cache(config)
    for i in range(12):
        c.put(hashlib.sha256(str(i).encode()).hexdigest(), {"ok": True, "value": "x" * 160})
        assert c.stats()["disk_bytes"] <= 600
        assert c.stats()["memory_bytes"] <= 500
        assert c.stats()["disk_entries"] <= 2
    key = hashlib.sha256(b"11").hexdigest()
    assert Cache(config).get(key)["payload"]["value"] == "x" * 160
    for p in tmp_path.glob("*.json"):
        os.utime(p, (0, 0))
    c.prune()
    assert c.stats()["disk_bytes"] == 0


def test_cache_never_grows_for_oversized_or_invalid_json(tmp_path):
    c = Cache(Config(cache_dir=tmp_path, entry_bytes=100))
    c.put("a", {"data": "x" * 1000})
    assert c.stats()["disk_bytes"] == 0
    with pytest.raises(ValueError):
        c.put("b", {"bad": float("nan")})


def test_bad_expiration_does_not_disable_provider_for_other_symbols(gateways):
    def source(**kwargs):
        if kwargs["expiration"]:
            raise GatewayError("Unknown expiration")
        return data(**kwargs)

    g = gateways({"test": source})
    assert not g.options_chain("AAPL", 2000000000)["ok"]
    assert g.options_chain("TSLA")["ok"]


def chain():
    expiration = 1893456000

    def row(kind):
        return {
            "contractSymbol": f"AAPL300101{kind}00100000",
            "strike": 100,
            "expiration": expiration,
            "bid": 2,
            "ask": 3,
            "delta": 0.4 if kind == "C" else -0.6,
        }

    return {
        "expirationDates": [expiration],
        "quote": {"symbol": "AAPL", "regularMarketPrice": 100},
        "options": [{"expirationDate": expiration, "calls": [row("C")], "puts": [row("P")]}],
    }


def test_normalization_preserves_quotes_and_missing_timestamps():
    r = normalize("AAPL", "yahoo", chain(), 1893456000)
    assert r["data"]["calls"][0]["bid"] == 2
    assert r["data"]["calls"][0]["ask"] == 3
    assert r["gateway"]["quote_time_known"] is False
    assert r["gateway"]["source_timestamp"] is None


@pytest.mark.parametrize("corruption", ["identity", "expiration", "crossed", "missing", "contract", "empty"])
def test_bad_snapshots_are_never_cached_as_usable(corruption):
    raw = chain()
    if corruption == "identity":
        raw["quote"]["symbol"] = "TSLA"
    if corruption == "expiration":
        raw["options"][0]["expirationDate"] += 86400
    if corruption == "crossed":
        raw["options"][0]["calls"][0]["bid"] = 4
    if corruption == "missing":
        raw["quote"]["regularMarketPrice"] = None
    if corruption == "contract":
        raw["options"][0]["calls"][0]["contractSymbol"] = "AAPL1300101C00100000"
    if corruption == "empty":
        raw["options"] = []
    with pytest.raises(GatewayError):
        normalize("AAPL", "yahoo", raw, 1893456000)


def test_expired_memory_is_reclaimed_without_more_reads(tmp_path, monkeypatch):
    import src.data_gateway.cache as module

    c = Cache(Config(cache_dir=tmp_path, ttl=1, stale_ttl=2))
    c.put("a", {"ok": True})
    now = time.time()
    monkeypatch.setattr(module.time, "time", lambda: now + 3)
    c.prune()
    assert c.stats()["memory_bytes"] == 0
    assert c.stats()["disk_bytes"] == 0


def test_pending_unique_requests_are_bounded(gateways):
    entered, release = threading.Event(), threading.Event()

    def provider(**kwargs):
        entered.set()
        release.wait(2)
        return data(**kwargs)

    g = gateways({"test": provider}, pending=1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(g.options_chain, "AAPL")
        assert entered.wait(1)
        assert not g.options_chain("NVDA")["ok"]
        assert g.status()["active_requests"] == 1
        release.set()
        assert first.result()["ok"]


def test_full_expiry_does_not_silently_keep_only_nearby_strikes():
    raw = chain()
    for side, letter in (("calls", "C"), ("puts", "P")):
        template = raw["options"][0][side][0]
        raw["options"][0][side] = [
            dict(template, strike=i, contractSymbol=f"AAPL300101{letter}{i * 1000:08d}") for i in range(1, 301)
        ]
    short = normalize("AAPL", "cboe", raw, None)
    full = normalize("AAPL", "cboe", raw, None, full=True)
    assert short["data"]["calls_count"] == 120
    assert not short["data"]["complete_expiration"]
    assert full["data"]["calls_count"] == full["data"]["puts_count"] == 300
    assert full["data"]["complete_expiration"]
    assert full["gateway"]["quality"] == "delayed"


def test_idle_memory_is_silently_reclaimed_even_if_disk_is_still_fresh(tmp_path, monkeypatch):
    import src.data_gateway.cache as module

    c = Cache(Config(cache_dir=tmp_path, memory_idle=10, stale_ttl=900))
    c.put("idle", {"ok": True})
    now = time.monotonic()
    monkeypatch.setattr(module.time, "monotonic", lambda: now + 11)
    c.prune()
    assert c.stats()["memory_entries"] == 0
    assert not c.last_access and c.memory_size == 0
    assert c.stats()["disk_entries"] == 1
    assert c.get("idle")["payload"]["ok"]  # repopulate only on actual demand


def test_idle_cleanup_runs_without_any_followup_request(gateways):
    g = gateways({"test": data}, memory_idle=0.02, cleanup_interval=0.01)
    assert g.options_chain("AAPL")["ok"]
    deadline = time.monotonic() + 1
    while g.cache.stats()["memory_entries"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert g.cache.stats()["memory_entries"] == 0
    assert g.cache.stats()["disk_entries"] == 1


def test_partial_result_is_not_retained_as_a_fresh_complete_request(tmp_path):
    calls = []

    def provider(**kwargs):
        calls.append(1)
        return {"ok": True, "complete": len(calls) > 1, "data": {"rows": [1]}}

    gateway = MarketDataGateway(Config(tmp_path), {"bars": {"test": provider}})
    try:
        first = gateway.request("bars", {})
        assert first["ok"] and not first["complete"]
        assert gateway.cache.stats()["memory_entries"] == 0
        second = gateway.request("bars", {})
        assert second["complete"] and len(calls) == 2
        assert second["gateway"]["cache"] == "miss"
    finally:
        gateway.close()
