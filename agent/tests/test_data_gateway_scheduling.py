"""Capacity protection and scan recovery under controlled source failures."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from src.data_gateway.config import Config
from src.data_gateway.scans import ScanQueue
from src.data_gateway.scheduling import RequestQueue, background, SourcePacer
from src.data_gateway.service import MarketDataGateway, GatewayBusy


def test_background_yields_between_sources_without_another_worker(tmp_path):
    from src.data_gateway.fanout import SourceCall, acquire_groups

    gateway = MarketDataGateway(replace(Config(tmp_path), source_spacing=0))
    entered, release = threading.Event(), threading.Event()
    order = []

    def first():
        entered.set()
        release.wait(2)
        order.append("scan-first")

    def scan():
        yield SourceCall("scan", first, 1)
        yield SourceCall("scan", lambda: order.append("scan-second"), 1)
        return "complete"

    token = background.set(True)
    active = gateway.coordinators.submit(
        lambda: acquire_groups(gateway, [scan()], time.monotonic() + 2, parallel=False)
    )
    try:
        assert entered.wait(1)
        history = gateway.coordinators.submit(gateway.invoke, lambda: order.append("history"), {}, 0.5)
        background.reset(token)
        assert gateway.coordinators.submit(lambda: "foreground").result(0.5) == "foreground"
        assert not history.done()
        release.set()
        assert active.result(2) == ["complete"]
        history.result(1)
        assert order == ["scan-first", "history", "scan-second"]
        assert gateway.coordinators.status()["background_yields"] == 1
        assert len(gateway.coordinators.threads) == 2
        assert gateway.config.workers == 4 and gateway.config.pending == 16
    finally:
        release.set()
        gateway.close()


def test_background_cooperation_never_recursively_drains_the_queue():
    queue = RequestQueue(2, 16)
    entered, release = threading.Event(), threading.Event()
    order = []

    def scan():
        entered.set()
        release.wait(2)
        queue.cooperate()
        order.append("scan-resumed")

    def history():
        queue.cooperate()  # Must not add another suspended frame/context.
        order.append("history")

    token = background.set(True)
    try:
        active = queue.submit(scan)
        assert entered.wait(1)
        next_job = queue.submit(history)
        last = queue.submit(lambda: order.append("last"))
        release.set()
        for future in (active, next_job, last):
            future.result(1)
        assert order == ["history", "scan-resumed", "last"]
    finally:
        background.reset(token)
        release.set()
        queue.shutdown(wait=True)


def test_suspended_scan_keeps_its_original_deadline(tmp_path):
    from src.data_gateway.fanout import SourceCall, acquire_groups

    gateway = MarketDataGateway(replace(Config(tmp_path), source_spacing=0))
    entered, release = threading.Event(), threading.Event()
    calls = []

    def first():
        entered.set()
        release.wait(1)

    def scan():
        yield SourceCall("scan", first, 1)
        try:
            yield SourceCall("scan", lambda: calls.append("expired"), 1)
        except GatewayBusy:
            return "deadline"

    token = background.set(True)
    try:
        active = gateway.coordinators.submit(
            lambda: acquire_groups(gateway, [scan()], time.monotonic() + 0.15, parallel=False)
        )
        assert entered.wait(1)
        history = gateway.coordinators.submit(time.sleep, 0.2)
        release.set()
        assert active.result(1) == ["deadline"]
        history.result(1)
        assert calls == []
    finally:
        background.reset(token)
        release.set()
        gateway.close()


def test_background_timeout_cannot_start_another_source_until_actual_exit(tmp_path):
    from src.data_gateway.fanout import SourceCall, acquire_groups

    gateway = MarketDataGateway(replace(Config(tmp_path), source_spacing=0, source_timeout=0.02))
    release = threading.Event()
    calls = []

    def route():
        try:
            yield SourceCall("slow", lambda: release.wait(1), 1)
        except TimeoutError:
            pass
        try:
            yield SourceCall("fallback", lambda: calls.append("fallback"), 1)
        except GatewayBusy:
            return "capacity"

    token = background.set(True)
    try:
        assert acquire_groups(gateway, [route()], time.monotonic() + 0.08, parallel=False) == ["capacity"]
        assert calls == []
        assert gateway.router.status() == []  # Admission pressure is not source health.
        background.reset(token)
        assert gateway.invoke(lambda: "foreground", {}, 0.2) == "foreground"
    finally:
        release.set()
        gateway.close()


def test_background_cannot_consume_foreground_coordinator():
    queue = RequestQueue(2, 16)
    entered, release = threading.Event(), threading.Event()
    token = background.set(True)

    def hold():
        entered.set()
        release.wait(2)

    try:
        first = queue.submit(hold)
        assert entered.wait(1)
        second = queue.submit(lambda: "background")
        background.reset(token)
        foreground = queue.submit(lambda: "foreground")
        assert foreground.result(0.5) == "foreground"
        assert not second.done()
        release.set()
        first.result(1)
        assert second.result(1) == "background"
    finally:
        release.set()
        queue.shutdown(wait=True)


def test_timed_out_background_source_keeps_its_one_slot(tmp_path):
    g = MarketDataGateway(Config(tmp_path))
    release = threading.Event()
    token = background.set(True)
    try:
        try:
            g.invoke(lambda: release.wait(2), {}, 0.01)
        except TimeoutError:
            pass
        try:
            g.invoke(lambda: None, {}, 0.1)
            assert False, "background must not accumulate timed-out workers"
        except GatewayBusy:
            pass
        background.reset(token)
        assert g.invoke(lambda: "live", {}, 0.2) == "live"
    finally:
        release.set()
        g.close()


def test_expired_queued_requests_never_reach_source(tmp_path):
    release, entered = threading.Event(), threading.Event()
    calls = []

    def source(ticker, **kwargs):
        calls.append(ticker)
        entered.set()
        release.wait(1)
        return {"ok": True}

    config = replace(Config(tmp_path), workers=1, sources=("test",), request_timeout=0.06, source_timeout=0.2)
    g = MarketDataGateway(config, {"options_chain": {"test": source}})
    try:
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(g.options_chain, "AAPL")
            assert entered.wait(1)
            second = pool.submit(g.options_chain, "MSFT")
            assert not first.result()["ok"] and not second.result()["ok"]
            release.set()
        time.sleep(0.05)
        assert calls == ["AAPL"]
    finally:
        release.set()
        g.close()


def test_scan_retries_missing_symbols_without_repeating_successes():
    calls = []
    config = replace(Config(Path("/tmp/unused")), cooldown=0.01, scan_spacing=0.001)

    def bars(**params):
        codes = params["codes"]
        first = not calls
        calls.extend(codes)
        accepted = [code for code in codes if not (first and code == "AAPL.US")]
        return {"ok": bool(accepted), "data": {"_provenance": {code: {"source": "test"} for code in accepted}}}

    queue = ScanQueue(SimpleNamespace(config=config, bars=bars))
    try:
        job = queue.create(["AAPL.US", "MSFT.US"], start_date="2026-01-01", end_date="2026-01-03")
        until = time.monotonic() + 2
        while time.monotonic() < until and queue.status(job["id"])["state"] != "complete":
            time.sleep(0.01)
        final = queue.status(job["id"])
        assert final["state"] == "complete" and final["completed"] == 2
        assert calls.count("MSFT.US") == 1 and calls.count("AAPL.US") == 2
    finally:
        queue.close()


def test_source_spacing_is_shared_across_threads():
    pacer = SourcePacer(0.02)
    stamps = []

    def acquire():
        assert pacer.acquire("test", time.monotonic() + 1)
        stamps.append(time.monotonic())

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: acquire(), range(4)))
    assert all(b - a >= 0.018 for a, b in zip(sorted(stamps), sorted(stamps)[1:]))


def test_cancelled_subscribers_keep_capacity_until_threads_exit(tmp_path):
    import asyncio
    from src.data_gateway.streams import StreamHub

    async def run():
        release = threading.Event()
        calls = []

        def acquire():
            calls.append(1)
            release.wait(2)

        hub = StreamHub(SimpleNamespace(config=Config(tmp_path)))
        try:
            tasks = [asyncio.create_task(hub._acquire(acquire)) for _ in range(64)]
            await asyncio.sleep(0.05)
            assert len(calls) == 2
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            replacement = asyncio.create_task(hub._acquire(acquire))
            await asyncio.sleep(0.03)
            assert len(calls) == 2
            release.set()
            await asyncio.wait_for(replacement, 1)
            assert len(calls) == 3
        finally:
            release.set()
            await hub.close()

    asyncio.run(run())


def test_daily_weekly_watchlists_share_one_source_frame(tmp_path):
    from datetime import date
    from src.data_gateway.streams import StreamHub, Topic

    calls = []

    def acquire(**params):
        calls.append(params)
        return {
            "ok": True,
            "data": {
                "AAPL.US": [
                    {"trade_date": "2026-11-02", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 2},
                    {"trade_date": "2026-11-03", "open": 11, "high": 14, "low": 10, "close": 13, "volume": 3},
                ],
                "_provenance": {"AAPL.US": {"source": "test", "volume_unit": "shares"}},
            },
        }

    g = MarketDataGateway(Config(tmp_path), {"bars": {"test": acquire}})
    hub = StreamHub(g)
    try:
        daily = hub._bar_snapshot(Topic.parse("bars:AAPL.US:1D"), date(2026, 11, 14), 40)
        weekly = hub._bar_snapshot(Topic.parse("bars:AAPL.US:1W"), date(2026, 11, 14), 40)
        assert len(calls) == 1 and calls[0]["interval"] == "1D"
        assert len(daily["data"]["AAPL.US"]) == 2
        assert weekly["data"]["AAPL.US"] == [
            {"trade_date": "2026-11-03", "open": 10, "high": 14, "low": 9, "close": 13, "volume": 5}
        ]
        assert weekly["data"]["_provenance"] == daily["data"]["_provenance"]
    finally:
        g.close()


def test_loader_network_failure_is_not_an_empty_symbol(monkeypatch):
    from backtest.loaders.tencent_loader import DataLoader
    from src.market_data import fetch_market_data

    def fail(*args, **kwargs):
        try:
            raise OSError("transport body must not escape")
        except OSError as cause:
            raise ValueError("wrapped failure") from cause

    monkeypatch.setattr(DataLoader, "_fetch_one", fail)
    value = fetch_market_data(
        codes=["601398.SH"],
        start_date="2026-11-01",
        end_date="2026-11-03",
        source="tencent",
        include_provenance=True,
        max_fallback_attempts=1,
        loader_resolver=lambda _: DataLoader,
    )
    assert value["_diagnostics"]["601398.SH"]["attempts"][0]["reason"] == "network_failure"
    monkeypatch.setattr(DataLoader, "_fetch_one", lambda *a, **k: None)
    empty = fetch_market_data(
        codes=["601398.SH"],
        start_date="2026-11-01",
        end_date="2026-11-03",
        source="tencent",
        include_provenance=True,
        max_fallback_attempts=1,
        loader_resolver=lambda _: DataLoader,
    )
    assert empty["_diagnostics"]["601398.SH"]["attempts"][0]["reason"] == "no_data"


def test_cancelled_queue_entries_do_not_accumulate_under_churn():
    queue = RequestQueue(1, 2)
    release, entered = threading.Event(), threading.Event()

    def hold():
        entered.set()
        release.wait(2)

    try:
        active = queue.submit(hold)
        assert entered.wait(1)
        for _ in range(64):
            future = queue.submit(lambda: None)
            assert future.cancel()
        release.set()
        active.result(1)
    finally:
        release.set()
        queue.shutdown(wait=True)


def test_baostock_session_prefers_live_reads_but_does_not_starve_history(monkeypatch):
    import backtest.loaders.baostock_loader as loader
    from backtest.loaders.base import source_background

    monkeypatch.setattr(loader, "_FOREGROUND_BURST", 0)
    order = []

    def task(name, low):
        token = source_background.set(low)
        try:
            with loader._session_admission(2) as admitted:
                assert admitted is not None
                order.append(name)
        finally:
            source_background.reset(token)

    token = source_background.set(True)
    with ThreadPoolExecutor(6) as pool:
        with loader._session_admission(2) as admitted:
            assert admitted is not None
            futures = [pool.submit(task, "history", True)]
            futures += [pool.submit(task, f"live-{i}", False) for i in range(5)]
            until = time.monotonic() + 1
            while len(loader._SESSION_WAITERS) < 6 and time.monotonic() < until:
                time.sleep(0.001)
            assert len(loader._SESSION_WAITERS) == 6
        for future in futures:
            future.result(2)
    source_background.reset(token)
    assert all(name.startswith("live-") for name in order[:4])
    assert order[4] == "history" and order[5].startswith("live-")


def test_bulk_scan_reuses_one_source_session_per_batch(tmp_path, monkeypatch):
    import pandas as pd
    from backtest.loaders import registry

    registry._ensure_registered()
    calls = []

    class Loader:
        name = "tencent"

        def is_available(self):
            return True

        def fetch(self, codes, *args, **kwargs):
            calls.append(codes)
            frame = pd.DataFrame(
                {k: [1.0, 2.0] for k in ["open", "high", "low", "close", "volume"]},
                index=pd.date_range("2026-11-02", periods=2),
            )
            frame.index.name = "trade_date"
            return {code: frame for code in codes}

    monkeypatch.setitem(registry.LOADER_REGISTRY, "tencent", Loader)
    gateway = MarketDataGateway(Config(tmp_path))
    try:
        result = gateway.bars(codes=["601398.SH", "600519.SH"], start_date="2026-11-01", end_date="2026-11-03")
        assert result["ok"] and not result["data"]["_unresolved"]
        assert set(result["data"]["_coverage"]) == {"601398.SH", "600519.SH"}
        assert len(calls) == 1 and set(calls[0]) == {"601398.SH", "600519.SH"}
    finally:
        gateway.close()


def test_partial_scan_does_not_cool_down_unrelated_ready_symbols():
    calls = []
    ready = threading.Event()
    config = replace(Config(Path("/tmp/unused")), cooldown=30, scan_spacing=0.001)
    codes = [f"{600000 + i}.SH" for i in range(16)]

    def bars(**params):
        calls.append(params["codes"])
        accepted = [code for code in params["codes"] if code != codes[0]]
        if codes[-1] in accepted:
            ready.set()
        return {"ok": bool(accepted), "data": {"_provenance": {c: {} for c in accepted}}}

    queue = ScanQueue(SimpleNamespace(config=config, bars=bars))
    try:
        job = queue.create(codes, start_date="2026-01-01", end_date="2026-01-03")
        assert ready.wait(1), "one missing symbol blocked the next healthy batch"
        assert codes[0] not in calls[1]  # Its 30-second retry deadline remains enforced.
        queue.cancel(job["id"])
    finally:
        queue.close()


def test_batch_keeps_successful_rows_when_first_symbol_is_missing(tmp_path, monkeypatch):
    import pandas as pd
    from backtest.loaders import registry

    registry._ensure_registered()
    calls = []

    class Loader:
        name = "tencent"

        def is_available(self):
            return True

        def fetch(self, codes, *args, **kwargs):
            calls.append(list(codes))
            frame = pd.DataFrame(
                {k: [1.0, 2.0] for k in ["open", "high", "low", "close", "volume"]},
                index=pd.date_range("2026-11-02", periods=2),
            )
            frame.index.name = "trade_date"
            return {code: frame for code in codes if code != "600000.SH"}

    monkeypatch.setitem(registry.LOADER_REGISTRY, "tencent", Loader)
    gateway = MarketDataGateway(Config(tmp_path))
    try:
        result = gateway.bars(
            codes=["600000.SH", "600519.SH"],
            start_date="2026-11-01",
            end_date="2026-11-03",
            source="tencent",
            exact_source=True,
        )
        assert result["ok"] and result["data"]["_unresolved"] == ["600000.SH"]
        assert "600519.SH" in result["data"]["_coverage"]
        assert calls == [["600000.SH", "600519.SH"]]
    finally:
        gateway.close()


def test_scan_respects_short_capacity_retry_without_weakening_network_backoff():
    config = replace(Config(Path("/tmp/unused")), cooldown=30, scan_spacing=0.001)
    calls = []
    recovered = threading.Event()

    def bars(**params):
        calls.append(time.monotonic())
        if len(calls) == 1:
            return {"ok": False, "retry_after_seconds": 0.02, "error": "source_busy"}
        recovered.set()
        return {"ok": True, "data": {"_provenance": {"600000.SH": {}}}}

    queue = ScanQueue(SimpleNamespace(config=config, bars=bars))
    try:
        queue.create(["600000.SH"], start_date="2026-01-01", end_date="2026-01-03")
        assert recovered.wait(1), "local capacity release incorrectly waited the network cooldown"
        assert calls[1] - calls[0] >= 0.018
    finally:
        queue.close()


def test_serial_http_symbols_are_split_inside_unchanged_source_deadline(tmp_path, monkeypatch):
    import pandas as pd
    from backtest.loaders import registry

    registry._ensure_registered()
    calls = []

    class Loader:
        name = "yahoo"

        def is_available(self):
            return True

        def fetch(self, codes, *args, **kwargs):
            calls.append(list(codes))
            time.sleep(0.01 * len(codes))
            frame = pd.DataFrame(
                {k: [1.0, 2.0] for k in ["open", "high", "low", "close", "volume"]},
                index=pd.date_range("2026-11-02", periods=2),
            )
            frame.index.name = "trade_date"
            return {code: frame for code in codes}

    monkeypatch.setitem(registry.LOADER_REGISTRY, "yahoo", Loader)
    config = replace(Config(tmp_path), source_timeout=0.075, request_timeout=1, source_spacing=0)
    gateway = MarketDataGateway(config)
    codes = ["AAPL.US", "MSFT.US", "NVDA.US", "AMZN.US", "META.US", "GOOGL.US", "TSLA.US", "SPY.US"]
    try:
        value = gateway.bars(
            codes=codes, start_date="2026-11-01", end_date="2026-11-03", source="yahoo", exact_source=True
        )
        assert value["ok"] and not value["data"]["_unresolved"]
        assert len(calls) == 2 and all(len(batch) == 4 for batch in calls)
        assert gateway.config.source_timeout == 0.075 and gateway.config.workers == 4
    finally:
        gateway.close()


def test_queued_timeout_is_local_pressure_not_network_cooldown(tmp_path):
    config = replace(Config(tmp_path), workers=1, request_timeout=0.03)
    gateway = MarketDataGateway(config)
    release = threading.Event()
    occupied = gateway.coordinators.submit(release.wait, 1)
    try:
        result = gateway.options_chain("AAPL")
        assert not result["ok"] and result["retry_after_seconds"] == 1
        assert not gateway.router.health
    finally:
        release.set()
        occupied.result(1)
        gateway.close()


def test_six_cold_markets_share_existing_slots_after_foreground_queue_wait(tmp_path, monkeypatch):
    """Replay queue wait plus serial cross-market work without retries or more slots."""
    import pandas as pd
    from backtest.loaders import registry

    registry._ensure_registered()
    activity = {"active": 0, "peak": 0, "calls": 0}
    lock = threading.Lock()
    release, entered = threading.Event(), threading.Event()

    class Loader:
        name = "yahoo"

        def is_available(self):
            return True

        def fetch(self, codes, *args, **kwargs):
            with lock:
                activity["active"] += 1
                activity["peak"] = max(activity["peak"], activity["active"])
                activity["calls"] += 1
            try:
                time.sleep(1.4)
                frame = pd.DataFrame(
                    {k: [1.0, 2.0] for k in ("open", "high", "low", "close", "volume")},
                    index=pd.date_range("2026-11-02", periods=2),
                )
                frame.index.name = "trade_date"
                return {code: frame for code in codes}
            finally:
                with lock:
                    activity["active"] -= 1

    monkeypatch.setitem(registry.LOADER_REGISTRY, "yahoo", Loader)
    gateway = MarketDataGateway(Config(tmp_path))

    def hold_source():
        entered.set()
        release.wait(20)

    token = background.set(True)
    blocked = gateway.coordinators.submit(gateway.invoke, hold_source, {}, 20)
    background.reset(token)
    try:
        assert entered.wait(1)
        queued = gateway.coordinators.submit(time.sleep, 7.595)
        value = gateway.bars(
            codes=["AAPL.US", "00700.HK", "TD.TO", "VOD.L", "601398.SH", "BTC-USDT"],
            start_date="2026-11-02",
            end_date="2026-11-03",
            source="yahoo",
            exact_source=True,
        )
        assert value.get("complete") is True, value
        assert len(value["data"]["_provenance"]) == 6
        assert activity["calls"] == 6  # No request/source replay to hide the deadline.
        assert 1 < activity["peak"] <= 2  # Two reserved slots remain for background and quotes.
        assert len(gateway.coordinators.threads) == 2
        assert gateway.config.workers == 4 and gateway.config.pending == 16
        queued.result(1)
    finally:
        release.set()
        blocked.result(2)
        gateway.close()


def test_fanout_timeout_keeps_slots_until_actual_sources_exit(tmp_path):
    from src.data_gateway.fanout import SourceCall, acquire_groups

    gateway = MarketDataGateway(replace(Config(tmp_path), source_timeout=0.04, source_spacing=0))
    release = threading.Event()
    entered = []

    def slow():
        entered.append(1)
        release.wait(2)

    def route():
        try:
            yield SourceCall("slow", slow, 1)
        except TimeoutError:
            return {"timed_out": True}

    try:
        result = acquire_groups(gateway, [route(), route()], time.monotonic() + 0.2, parallel=True)
        assert result == [{"timed_out": True}, {"timed_out": True}]
        assert len(entered) == 2
        assert not gateway.fanout_slots.acquire(blocking=False)
        assert gateway.invoke(lambda: "foreground", {}, 0.1) == "foreground"
        release.set()
        assert gateway.fanout_slots.acquire(timeout=1)
        assert gateway.fanout_slots.acquire(timeout=1)
        gateway.fanout_slots.release()
        gateway.fanout_slots.release()
    finally:
        release.set()
        gateway.close()


def test_shared_fanout_leaves_both_background_and_interactive_source_capacity(tmp_path):
    gateway = MarketDataGateway(Config(tmp_path))
    release = threading.Event()
    futures = []
    try:
        futures = [gateway.submit_source(release.wait, {"timeout": 2}, 2, shared_bulk=True) for _ in range(2)]
        try:
            gateway.submit_source(lambda: None, {}, 0.1, shared_bulk=True)
            assert False, "A third fan-out source would steal the reserved slots"
        except GatewayBusy:
            pass
        token = background.set(True)
        try:
            futures.append(gateway.submit_source(release.wait, {"timeout": 2}, 2))
        finally:
            background.reset(token)
        assert gateway.invoke(lambda: "quote", {}, 0.1) == "quote"
    finally:
        release.set()
        for future in futures:
            future.result(1)
        gateway.close()


def test_scan_admits_one_http_batch_per_request():
    config = Config(Path("/tmp/unused"))
    seen = []
    finished = threading.Event()
    codes = [f"{600000 + i}.SH" for i in range(12)]

    def bars(**params):
        seen.append(params["codes"])
        if codes[-1] in params["codes"]:
            finished.set()
        return {"ok": True, "data": {"_provenance": {c: {} for c in params["codes"]}}}

    queue = ScanQueue(SimpleNamespace(config=config, bars=bars))
    try:
        queue.create(codes, start_date="2026-11-02", end_date="2026-11-13")
        assert finished.wait(2)
        assert [c for batch in seen for c in batch] == codes
        assert all(len(batch) <= config.http_batch_symbols for batch in seen)
        assert config.request_timeout == 15 and config.source_timeout == 6
    finally:
        queue.close()


@pytest.mark.parametrize("reason", ["no_data", "network_failure"])
def test_missing_batch_members_are_attempted_only_once_per_source(tmp_path, monkeypatch, reason):
    import json
    from backtest.loaders import registry
    from src import market_data

    calls = []
    codes = ["600000.SH", "600001.SH", "600002.SH", "600003.SH"]
    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "FALLBACK_CHAINS", {"a_share": ["first", "second"]})
    monkeypatch.setattr(registry, "get_source_order_override", lambda market: None)
    monkeypatch.setattr(market_data, "detect_source", lambda code: "first")

    def fetch(**params):
        source, batch = params["source"], params["codes"]
        calls.append((source, list(batch)))
        accepted = [c for c in batch if source == "second" or c == codes[0]]
        return json.dumps({
            **{c: [{"date": "2026-11-02", "close": 1}] for c in accepted},
            "_provenance": {c: {"source": source} for c in accepted},
            "_diagnostics": {c: {"attempts": [{"reason": reason}]} for c in batch if c not in accepted},
        })

    monkeypatch.setattr(market_data, "fetch_market_data_json", fetch)
    gateway = MarketDataGateway(replace(Config(tmp_path), source_spacing=0))
    try:
        result = gateway.bars(codes=codes, start_date="2026-11-02", end_date="2026-11-02")
        assert result["ok"] and not result["data"]["_unresolved"]
        assert calls == [("first", codes), ("second", codes[1:])]
        assert gateway.router.cooling("bars:a_share:1D", "first") == (reason == "network_failure")
    finally:
        gateway.close()


def test_scan_serial_fallback_finishes_without_retries_within_original_deadline(tmp_path, monkeypatch):
    """Two four-symbol HTTP calls cannot share one request's time budget."""
    import json
    from backtest.loaders import registry
    from src import market_data

    codes = [f"{600000 + i}.SH" for i in range(8)]
    calls = []
    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "FALLBACK_CHAINS", {"a_share": ["blocked", "healthy"]})
    monkeypatch.setattr(registry, "get_source_order_override", lambda market: None)
    monkeypatch.setattr(market_data, "detect_source", lambda code: "blocked")

    def fetch(**params):
        source, batch = params["source"], params["codes"]
        calls.append((source, list(batch)))
        if source == "blocked":
            raise ConnectionError("WAF rejection")
        time.sleep(0.025 * len(batch))
        return json.dumps({
            **{c: [{"date": "2026-11-02", "close": 1}] for c in batch},
            "_provenance": {c: {"source": source} for c in batch},
        })

    monkeypatch.setattr(market_data, "fetch_market_data_json", fetch)
    config = replace(Config(tmp_path), source_timeout=0.16, request_timeout=0.18, source_spacing=0, scan_spacing=0.001)
    gateway = MarketDataGateway(config)
    queue = ScanQueue(gateway)
    try:
        job = queue.create(codes, start_date="2026-11-02", end_date="2026-11-02")
        until = time.monotonic() + 2
        while time.monotonic() < until:
            value = queue.status(job["id"])
            if value["completed"] == len(codes) or value["retries"]:
                break
            time.sleep(0.01)
        assert value["completed"] == len(codes) and value["retries"] == 0, value
        assert [c for source, batch in calls if source == "healthy" for c in batch] == codes
    finally:
        queue.close()
        gateway.close()


def test_routable_baostock_read_does_not_queue_behind_active_history():
    import backtest.loaders.baostock_loader as loader
    from backtest.loaders.acquisition import source_can_fallback

    with loader._session_admission(1) as owner:
        assert owner is not None
        token = source_can_fallback.set(True)
        try:
            started = time.monotonic()
            with loader._session_admission(0.2) as blocked:
                assert blocked is None
            assert time.monotonic() - started < 0.1
            assert not loader._SESSION_WAITERS and loader._SESSION_ACTIVE
        finally:
            source_can_fallback.reset(token)
    token = source_can_fallback.set(True)
    try:
        with loader._session_admission(1) as free:
            assert free is not None
    finally:
        source_can_fallback.reset(token)


def test_auto_route_bypasses_busy_sdk_but_explicit_source_keeps_waiting(tmp_path, monkeypatch):
    import json
    import backtest.loaders.baostock_loader as loader
    from backtest.loaders import registry
    from src import market_data

    calls = []
    monkeypatch.setattr(registry, "LOADER_REGISTRY", {
        "baostock": lambda: SimpleNamespace(is_available=lambda: True),
        "healthy": lambda: SimpleNamespace(is_available=lambda: True),
    })
    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "FALLBACK_CHAINS", {"a_share": ["baostock", "healthy"]})
    monkeypatch.setattr(registry, "get_source_order_override", lambda market: None)
    monkeypatch.setattr(market_data, "detect_source", lambda code: "baostock")

    def fetch(**params):
        source, codes = params["source"], params["codes"]
        calls.append(source)
        if source == "baostock":
            with loader._session_admission(1) as admitted:
                if admitted is None:
                    return json.dumps({"_diagnostics": {c: {"attempts": [{"reason": "source_busy"}]} for c in codes}})
        return json.dumps({**{c: [{"date": "2026-11-02", "close": 1}] for c in codes},
                           "_provenance": {c: {"source": source} for c in codes}})

    monkeypatch.setattr(market_data, "fetch_market_data_json", fetch)
    gateway = MarketDataGateway(replace(Config(tmp_path), source_timeout=0.5, request_timeout=0.8, source_spacing=0))
    params = dict(codes=["601398.SH"], start_date="2026-11-02", end_date="2026-11-02")
    try:
        with loader._session_admission(1):
            started = time.monotonic()
            result = gateway.bars(**params)
            assert time.monotonic() - started < 0.2
            assert result["data"]["_provenance"]["601398.SH"]["source"] == "healthy"
            assert not gateway.router.cooling("bars:a_share:1D", "baostock")
            started = time.monotonic()
            exact = gateway.bars(**params, source="baostock", exact_source=True)
            assert time.monotonic() - started >= 0.2 and not exact["ok"]
        assert calls == ["baostock", "healthy", "baostock"]
    finally:
        gateway.close()
