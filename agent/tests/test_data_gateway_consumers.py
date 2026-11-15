"""Real consumer boundaries: shared acquisition, compatibility and resource caps."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import json
import threading
import time

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.data_gateway.config import Config
from src.data_gateway.service import MarketDataGateway, GatewayBusy
from src.data_gateway.reads import read, managed_reader, public_data_read


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    import src.data_gateway as module

    instance = MarketDataGateway(Config(cache_dir=tmp_path / "shared"))
    monkeypatch.setattr(module, "_instance", instance)
    yield instance
    instance.close()


def test_equal_public_reads_share_flight_and_snapshot(gateway):
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Reader:
        @public_data_read()
        def execute(self, **kwargs):
            calls.append(kwargs)
            entered.set()
            assert release.wait(2)
            return json.dumps({"rows": [1], "observed_at": "2026-11-13"})

    with ThreadPoolExecutor(2) as executor:
        first = executor.submit(Reader().execute, symbol="AAPL")
        assert entered.wait(1)
        second = executor.submit(Reader().execute, symbol="AAPL")
        release.set()
        assert first.result() == second.result()
    assert Reader().execute(symbol="AAPL") == first.result()
    assert len(calls) == 1
    assert gateway.status()["active_requests"] == 0


def test_failures_and_partial_reads_are_not_cached(gateway):
    calls = []
    for response in (
        {"error": "upstream unavailable"},
        {"complete": False, "rows": [1]},
        {"ok": True, "data": [{"error": "one market unavailable"}]},
    ):

        def fetch():
            calls.append(1)
            return json.dumps(response)

        for _ in range(2):
            assert read(gateway, "partial", {}, fetch) == json.dumps(response)
    assert len(calls) == 6


def test_uncached_instance_and_large_result_preserve_every_row(gateway):
    frame = pd.DataFrame(
        {"close": range(100_000)}, index=pd.date_range("2020-01-01", periods=100_000, freq="5min", tz="UTC")
    )
    frame.attrs = {"quote_currency": "USD", "adjustment": "raw"}
    result = read(gateway, "frames", {}, lambda: {"AAPL": frame}, cacheable=False)
    pd.testing.assert_frame_equal(result["AAPL"], frame)
    assert result["AAPL"].attrs == frame.attrs
    large = json.dumps({"rows": ["x" * 1000] * 3000})
    assert len(large) > gateway.config.entry_bytes
    assert read(gateway, "large", {}, lambda: large) == large
    assert not gateway.cache.memory
    assert not list(gateway.config.cache_dir.glob("*.json"))


def test_nested_reader_does_not_enqueue_behind_its_source(gateway):
    @managed_reader
    def inner():
        return "observed"

    class Reader:
        @public_data_read()
        def execute(self):
            return json.dumps({"value": inner()})

    assert json.loads(Reader().execute()) == {"value": "observed"}
    assert gateway.status()["active_requests"] == 0


def test_timeout_keeps_actual_source_slot_until_completion(tmp_path):
    release = threading.Event()
    gateway = MarketDataGateway(
        Config(cache_dir=tmp_path / "timeout", workers=1, source_timeout=0.05, request_timeout=0.2)
    )
    try:
        with pytest.raises(TimeoutError):
            read(gateway, "blocked", {}, lambda: release.wait(1), cacheable=False)
        with pytest.raises(GatewayBusy):
            read(gateway, "other", {}, lambda: "no", cacheable=False)
        assert gateway.config.memory_bytes == 8 * 1024**2
        assert gateway.config.disk_bytes == 64 * 1024**2
        release.set()
        limit = time.monotonic() + 1
        while not gateway.source_slots.acquire(blocking=False):
            assert time.monotonic() < limit
            time.sleep(0.005)
        gateway.source_slots.release()
        assert read(gateway, "recovered", {}, lambda: "yes", cacheable=False) == "yes"
    finally:
        release.set()
        gateway.close()


def test_api_and_agent_share_identical_bar_snapshot(gateway, monkeypatch):
    import src.data_gateway.api as api
    from src.tools.market_data_tool import MarketDataTool

    calls = []

    def bars(**params):
        calls.append(params)
        return {
            "ok": True,
            "complete": True,
            "data": {
                "AAPL.US": [{"date": "2026-11-12", "close": 200.0}],
                "_provenance": {"AAPL.US": {"source": "fixture", "quote_currency": "USD"}},
            },
        }

    gateway.providers["bars"] = {"fixture": bars}
    monkeypatch.setattr(api, "get_gateway", lambda: gateway)
    app = FastAPI()
    api.register_gateway_routes(app, lambda: None)
    params = {"codes": ["AAPL.US"], "start_date": "2026-11-12", "end_date": "2026-11-13", "max_rows": 250}
    response = TestClient(app).post("/data/bars", json=params)
    assert response.status_code == 200
    result = json.loads(MarketDataTool().execute(**params))
    assert result["AAPL.US"] == response.json()["data"]["AAPL.US"]
    assert result["_provenance"]["AAPL.US"]["source"] == "fixture"
    assert len(calls) == 1


def test_registered_loader_keeps_frame_attrs_and_exception(gateway):
    from backtest.loaders.registry import register, LOADER_REGISTRY

    @register
    class Loader:
        name = "gateway_test_only"

        def fetch(self, codes, start_date, end_date):
            if not codes:
                raise ValueError("empty symbols")
            frame = pd.DataFrame({"close": [12.0]}, index=pd.DatetimeIndex(["2026-11-12"], name="date"))
            frame.attrs["quote_currency"] = "CNY"
            return {codes[0]: frame}

    try:
        result = Loader().fetch(["600519.SH"], "2026-11-12", "2026-11-13")
        assert result["600519.SH"].attrs == {"quote_currency": "CNY"}
        with pytest.raises(ValueError, match="empty symbols"):
            Loader().fetch([], "2026-11-12", "2026-11-13")
    finally:
        LOADER_REGISTRY.pop(Loader.name)


def test_caller_mutation_cannot_change_another_snapshot(gateway):
    observed = {"rows": [{"close": 12}]}
    first = read(gateway, "json-reader", {}, lambda: observed)
    first["rows"][0]["close"] = 99
    second = read(gateway, "json-reader", {}, lambda: observed)
    assert second == {"rows": [{"close": 12}]}
    assert observed == second


def test_bundled_http_reader_uses_source_budget(gateway, monkeypatch):
    import requests
    from src.data_gateway.reads import public_http_get, owned_source

    def fetch(url, **kwargs):
        assert owned_source.get()
        assert 0 < kwargs["timeout"] <= gateway.config.source_timeout
        return "response"

    monkeypatch.setattr(requests, "get", fetch)
    assert public_http_get("https://example.invalid/public", timeout=30) == "response"
    assert gateway.status()["active_requests"] == 0


def test_large_analysis_universe_is_chunked_without_losing_errors(gateway):
    from src.data_gateway.reads import loader_read

    calls = []

    class Loader:
        name = "analysis"

        @loader_read
        def fetch(self, codes, start_date, end_date, *, interval="1D"):
            from src.data_gateway.scheduling import background

            assert background.get()  # bulk analysis leaves foreground capacity
            calls.append(list(codes))
            self.fetch_errors = {code: "unavailable" for code in codes if code.endswith("3")}
            return {code: pd.DataFrame({"close": [1.0]}) for code in codes if code not in self.fetch_errors}

    loader = Loader()
    symbols = [f"S{i}" for i in range(13)]
    result = loader.fetch(symbols, "2020-01-01", "2025-01-01", interval="5m")
    assert [code for batch in calls for code in batch] == symbols
    assert max(map(len, calls)) <= gateway.config.http_batch_symbols
    assert set(result) == set(symbols) - {"S3"}
    assert loader.fetch_errors == {"S3": "unavailable"}
    assert gateway.config.source_timeout == 6
    assert gateway.config.request_timeout == 15
