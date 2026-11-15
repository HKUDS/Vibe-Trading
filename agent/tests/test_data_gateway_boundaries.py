"""Regression guards for application entrypoints and executable skill examples."""

import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data_gateway.config import Config
from src.data_gateway.reads import (
    availability_probe,
    current_gateway,
    managed_async_reader,
    owned_source,
)
from src.data_gateway.service import MarketDataGateway

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "agent/src/skills"


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    import src.data_gateway as module

    instance = MarketDataGateway(Config(cache_dir=tmp_path / "cache"))
    monkeypatch.setattr(module, "_instance", instance)
    yield instance
    instance.close()


def test_vendor_clients_construct_and_materialize_inside_gateway(gateway, monkeypatch):
    from src.data_gateway.skill_sources import tushare_client, tushare_bar, yahoo_ticker, yahoo_download, akshare_query

    frame = pd.DataFrame({"close": [12.0]})

    def endpoint(*args, **kwargs):
        assert owned_source.get()
        assert current_gateway.get() is gateway
        return frame

    def client(token):
        assert owned_source.get()
        assert token == "test-token"
        return SimpleNamespace(daily=endpoint)

    monkeypatch.setitem(sys.modules, "tushare", SimpleNamespace(pro_api=client, pro_bar=endpoint))
    reader = tushare_client("test-token")
    pd.testing.assert_frame_equal(reader.daily(ts_code="600519.SH"), frame)
    pd.testing.assert_frame_equal(tushare_bar(ts_code="600519.SH", api=reader), frame)
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_zh_a_hist=endpoint))
    pd.testing.assert_frame_equal(akshare_query("stock_zh_a_hist", symbol="600519"), frame)

    class LazyInfo:
        def keys(self):
            assert owned_source.get()
            return ["lastPrice"]

        def __getitem__(self, key):
            assert owned_source.get()
            return 12

    class Ticker:
        def __init__(self, symbol):
            assert owned_source.get()

        @property
        def fast_info(self):
            return LazyInfo()

        @property
        def financials(self):
            assert owned_source.get()
            return frame

    def download(*args, **kwargs):
        assert owned_source.get()
        assert kwargs["threads"] is False
        return frame

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=Ticker, download=download))
    assert yahoo_ticker("AAPL").fast_info == {"lastPrice": 12}
    pd.testing.assert_frame_equal(yahoo_ticker("AAPL").financials, frame)
    pd.testing.assert_frame_equal(yahoo_download("AAPL", threads=True), frame)
    with pytest.raises(AttributeError, match="managed_reader"):
        yahoo_ticker("AAPL").funds_data
    assert gateway.status()["cache"]["disk_entries"] == 0


def test_two_coordinators_can_probe_without_self_queue_deadlock(tmp_path, monkeypatch):
    gateway = MarketDataGateway(Config(cache_dir=tmp_path / "nested", source_timeout=0.3, request_timeout=1))
    entered = threading.Barrier(2)

    @availability_probe
    def probe():
        assert owned_source.get()
        assert current_gateway.get() is gateway
        return True

    def historical(**params):
        entered.wait(timeout=1)
        assert probe()
        return {"ok": True, "data": params}

    monkeypatch.setattr(gateway, "_historical_bars", historical)
    gateway.providers["bars"] = {"existing_routes": historical}
    import src.data_gateway as module

    monkeypatch.setattr(module, "get_gateway", lambda: pytest.fail("Must use the current gateway, not another pool"))
    try:
        with ThreadPoolExecutor(2) as callers:
            futures = [callers.submit(gateway.request, "bars", {"symbol": symbol}) for symbol in ["A", "B"]]
            assert all(f.result()["ok"] for f in futures)
        assert gateway.status()["active_requests"] == 0
    finally:
        gateway.close()


def test_custom_loader_hook_cannot_bypass_acquisition(gateway):
    from src.market_data import fetch_market_data

    class Loader:
        name = "fixture"

        def fetch(self, codes, start_date, end_date, **kwargs):
            assert owned_source.get()
            return {codes[0]: pd.DataFrame({"close": [12.0]}, index=pd.DatetimeIndex(["2026-11-12"], name="date"))}

    result = fetch_market_data(
        codes=["AAPL.US"],
        start_date="2026-11-12",
        end_date="2026-11-13",
        loader_resolver=lambda _: Loader,
        as_frames=True,
    )
    assert len(result["AAPL.US"]) == 1


def test_async_collector_uses_source_worker_and_cleans_up_on_timeout(gateway):
    completed = threading.Event()
    gateway.config = replace(gateway.config, source_timeout=0.05)

    @managed_async_reader
    async def collect():
        assert owned_source.get()
        assert threading.current_thread().name.startswith("gateway-source")
        try:
            await asyncio.sleep(5)
        finally:
            completed.set()

    with pytest.raises(TimeoutError):
        asyncio.run(collect())
    assert completed.wait(1)
    assert gateway.config.workers == 4
    assert gateway.config.memory_bytes == 8 * 1024**2
    assert gateway.config.disk_bytes == 64 * 1024**2


# These primitive calls require a lexical managed-reader boundary. Wrapped
# vendor clients and shared HTTP helpers have their own executable tests above.
RAW_CALL = re.compile(
    r"^(?:(?:requests|httpx)\.(?:get|post|request)|(?:yf|yfinance)\.(?:Ticker|download)|ts\.(?:pro_api|pro_bar)|ak\.\w+|(?:urllib\.request\.)?urlopen)$"
)
BOUNDARIES = {"managed_reader", "managed_async_reader", "public_data_read", "availability_probe"}


def unmanaged_calls(code):
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Some vendor references contain pre-existing ellipses/full-width
        # placeholders; still refuse a newly pasted direct provider call.
        return re.findall(r"(?:requests\.(?:get|post)|yf\.(?:Ticker|download)|ts\.(?:pro_api|pro_bar))\s*\(", code)
    failures = []

    def walk(node, bounded=False):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bounded |= any(ast.unparse(d).split("(")[0].split(".")[-1] in BOUNDARIES for d in node.decorator_list)
        if isinstance(node, ast.Call) and RAW_CALL.match(ast.unparse(node.func)) and not bounded:
            failures.append(f"{node.lineno}: {ast.unparse(node.func)}")
        for child in ast.iter_child_nodes(node):
            walk(child, bounded)

    walk(tree)
    return failures


def test_all_skill_scripts_and_markdown_examples_use_gateway():
    failures = []
    for path in SKILLS.rglob("*"):
        if path.suffix == ".py":
            blocks = [path.read_text()]
        elif path.suffix == ".md":
            blocks = [
                m[2]
                for m in re.finditer(r"^```([^\n]*)\n(.*?)^```[ \t]*$", path.read_text(), re.M | re.S)
                if m[1].strip() in {"python", "py", ""}
            ]
        else:
            continue
        for index, code in enumerate(blocks):
            failures.extend(f"{path.relative_to(SKILLS)} block {index}: {error}" for error in unmanaged_calls(code))
    assert failures == []


def test_guard_rejects_new_direct_reads_and_accepts_bounded_helpers():
    assert unmanaged_calls("import requests\nx = requests.get('https://example.invalid')")
    assert unmanaged_calls("import yfinance as yf\nx = yf.Ticker('AAPL').info")
    assert not unmanaged_calls(
        "@managed_reader\ndef read():\n    return requests.get('https://example.invalid').json()"
    )


def test_frontend_fetches_are_central_backend_clients():
    found = set()
    for path in (ROOT / "frontend/src").rglob("*"):
        if path.suffix not in {".ts", ".tsx"} or "__tests__" in path.parts:
            continue
        if re.search(r"\bfetch\s*\(", path.read_text()):
            found.add(path.relative_to(ROOT / "frontend/src").as_posix())
    assert found == {"lib/api.ts", "lib/apiAuth.ts"}


def test_mcp_has_no_private_provider_sdk_acquisition():
    tree = ast.parse((ROOT / "agent/mcp_server.py").read_text())
    vendors = {"requests", "httpx", "tushare", "akshare", "yfinance", "ccxt", "urllib.request"}
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module)
    assert not (imports & vendors)


def test_connector_market_reads_are_bounded_without_account_cache(gateway, monkeypatch):
    from src.trading import service

    profile = SimpleNamespace(id="fixture-read", connector="fixture", transport="broker_sdk", environment="paper")
    monkeypatch.setattr(service, "profile_by_id", lambda _: profile)
    monkeypatch.setattr(service, "_sdk_config", lambda profile, module, overrides: overrides)
    calls = []

    def quote(symbol, *, config):
        assert owned_source.get()
        calls.append(config["credential_ref"])
        return {"ok": True, "symbol": symbol, "price": len(calls)}

    monkeypatch.setattr(service, "_sdk_module", lambda _: SimpleNamespace(get_quote=quote))
    first = service.get_quote("AAPL", profile.id, credential_ref="scope-a")
    second = service.get_quote("AAPL", profile.id, credential_ref="scope-b")
    assert first["price"] == 1 and second["price"] == 2
    assert calls == ["scope-a", "scope-b"]
    assert gateway.status()["cache"]["disk_entries"] == 0
    for operation in ["get_account", "get_positions", "get_open_orders", "place_order", "cancel_order"]:
        assert not getattr(getattr(service, operation), "gateway_public_read", False)


def test_nonregistered_tushare_endpoint_uses_source_pool(gateway):
    from functools import partial
    from backtest.loaders.tushare import _call_with_backoff

    def query(endpoint, **kwargs):
        assert owned_source.get()
        assert current_gateway.get() is gateway
        return pd.DataFrame({"endpoint": [endpoint], "symbol": [kwargs["ts_code"]]})

    # Real Tushare dynamically exposes endpoints as functools.partial objects.
    result = _call_with_backoff(partial(query, "daily_basic"), ts_code="600519.SH")
    assert result.iloc[0].to_dict() == {"endpoint": "daily_basic", "symbol": "600519.SH"}


def test_baostock_valuation_session_materializes_before_releasing_slot(gateway, monkeypatch):
    from contextlib import contextmanager
    from backtest.loaders import baostock_loader, valuation_loader

    calls = []

    @contextmanager
    def guard(timeout):
        assert owned_source.get()
        assert 0 < timeout <= gateway.config.source_timeout
        yield True

    def login():
        assert owned_source.get()
        calls.append("login")
        return SimpleNamespace(error_code="0")

    def query(*args, **kwargs):
        assert owned_source.get()
        rows = iter([True, False])
        return SimpleNamespace(error_code="0", next=lambda: next(rows), get_row_data=lambda: ["2024-01-02", "12"])

    def logout():
        assert owned_source.get()
        calls.append("logout")

    monkeypatch.setattr(baostock_loader, "_baostock_socket_guard", guard)
    monkeypatch.setitem(sys.modules, "baostock", SimpleNamespace(login=login, logout=logout, query_history_k_data_plus=query))
    for code in ["sh.600000", "sz.000001"]:
        assert valuation_loader._baostock_valuation_rows(code, "date,peTTM", "2024-01-02", "2024-01-02") == [["2024-01-02", "12"]]
    assert calls == ["login", "logout", "login", "logout"]
