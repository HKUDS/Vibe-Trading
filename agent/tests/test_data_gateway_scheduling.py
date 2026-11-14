"""Capacity protection and scan recovery under controlled source failures."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import threading
import time
from types import SimpleNamespace

from src.data_gateway.config import Config
from src.data_gateway.scans import ScanQueue
from src.data_gateway.scheduling import RequestQueue, background, SourcePacer
from src.data_gateway.service import MarketDataGateway, GatewayBusy


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
