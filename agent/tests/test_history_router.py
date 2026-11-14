"""Persisted history must route broadly without weakening interval or coverage identity."""

from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from src.data_gateway import history_router as router
from src.data_gateway.routing import NetworkRouter


def bars(start, count, minutes=5):
    stamp = datetime.fromisoformat(start)
    return [
        {
            "trade_date": (stamp + timedelta(minutes=i * minutes)).isoformat(),
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.0,
            "volume": 5.0,
        }
        for i in range(count)
    ]


def test_existing_market_identities_and_minute_routes():
    for symbol, market in [
        ("VIC.VN", "vietnam_equity"),
        ("005930.KS", "kr_equity"),
        ("TD.TO", "ca_equity"),
        ("AAPL", "us_equity"),
        ("00700.HK", "hk_equity"),
        ("BTC-USDT", "crypto"),
        ("^SPX", "index"),
    ]:
        assert router.market_for(symbol) == market
        assert router.candidates(symbol, "1D")
    assert "yahoo" in router.candidates("AAPL.US", "1m")
    assert "yahoo" not in router.candidates("AAPL.US", "4H")
    assert router.candidates("BTCIRT", "5m") == ["nobitex"]
    assert router.candidates("BTC-USDT", "5m", "okx") == ["okx"]
    assert router.candidates("601398.SH", "5m")[0] == "baostock"


def test_planning_preserves_limits_and_week_boundaries():
    p = router.plan(["601398.SH"] * 1, "2021-11-14", "2026-11-13", "5m", "auto")
    assert p["chunks"] == 61
    p = router.plan([" Aapl.us "], "2026-09-01", "2026-11-13", "1W", "auto")
    assert p["spec"]["codes"] == ["AAPL.US"]
    for (_, _, end), (_, start, _) in zip(p["parts"], p["parts"][1:]):
        assert datetime.fromisoformat(end).weekday() == 6
        assert datetime.fromisoformat(start).weekday() == 0
    with pytest.raises(ValueError, match="4096"):
        router.plan(["BTC-USDT", "ETH-USDT"], "2017-01-01", "2026-01-01", "1m", "auto")
    with pytest.raises(ValueError):
        router.plan([{}], "2026-11-01", "2026-11-02", "1D", "auto")
    with pytest.raises(ValueError):
        router.plan(["aapl.us", "AAPL.US"], "2026-11-01", "2026-11-02", "1D", "auto")


def test_grid_verified_only_when_all_bars_are_present():
    rows = bars("2026-11-12", 288)
    _, meta = router._normalize(rows, "BTC-USDT", "2026-11-12", "2026-11-12", "5m", {"source": "okx"}, "crypto")
    assert meta["coverage_verified"] is True
    for bad in [rows[1:], rows[:-1], rows[:10] + rows[11:], rows + rows[-1:]]:
        with pytest.raises(ValueError):
            router._normalize(bad, "BTC-USDT", "2026-11-12", "2026-11-12", "5m", {"source": "okx"}, "crypto")
    with pytest.raises(ValueError, match="different bar interval"):
        router._normalize(
            bars("2026-11-12", 4, 60), "AAPL.US", "2026-11-12", "2026-11-12", "4H", {"source": "yahoo"}, "us_equity"
        )
    with pytest.raises(ValueError, match="calendar grid mismatch"):
        router._normalize(
            bars("2026-11-12", 2), "AAPL.US", "2026-11-12", "2026-11-12", "5m", {"source": "yahoo"}, "us_equity"
        )
    with pytest.raises(ValueError, match="outside"):
        router._normalize(
            bars("2026-11-12", 2), "AAPL.US", "2021-11-12", "2021-11-12", "5m", {"source": "yahoo"}, "us_equity"
        )


def test_route_failover_keeps_source_identity_and_never_mixes_venues(monkeypatch):
    calls = []

    def acquire(**kw):
        calls.append(kw)
        if kw["source"] == "first":
            return {"ok": False, "error": "No data"}
        symbol = kw["codes"][0]
        return {
            "ok": True,
            "data": {
                symbol: bars("2026-11-12", 288),
                "_provenance": {
                    symbol: {"source": "second", "adjustment": "raw", "quote_currency": "USD", "volume_unit": "shares"}
                },
            },
        }

    gateway = SimpleNamespace(bars=acquire, router=NetworkRouter())
    monkeypatch.setattr("src.data_gateway.get_gateway", lambda: gateway)
    monkeypatch.setattr(router, "candidates", lambda *args: ["first", "second"])
    rows, meta = router.fetch_chunk("AAPL.US", "2026-11-12", "2026-11-12", "5m")
    assert len(rows) == 288 and meta["source"] == "second"
    assert [row["source"] for row in meta["route_attempts"]] == ["first", "second"]
    assert all(call["exact_source"] and call["max_rows"] == 0 for call in calls)
    assert not gateway.router.cooling("history:us_equity:5m", "first")  # one missing symbol isn't network failure
    for change in ({"adjustment": "split"}, {"quote_currency": "CNY"}, {"volume_unit": "lots"}):
        assert not router._compatible(meta, meta | change, "us_equity")
    assert not router._compatible(meta, meta | {"source": "first"}, "crypto")
    assert router._compatible(meta, meta | {"source": "first"}, "us_equity")
    assert not router._compatible(
        meta | {"quote_currency": None}, meta | {"source": "first", "quote_currency": None}, "us_equity"
    )


def test_unverified_dataset_is_readable_but_never_marked_complete(tmp_path):
    from src.data_gateway.history_store import HistoryStore

    def fetch(*args):
        return [{"symbol": "AAPL.US", "time": "2026-11-12T14:30:00", "close": 10.0}], {
            "source": "yahoo",
            "coverage_verified": False,
        }

    store = HistoryStore(tmp_path, fetcher=fetch)
    try:
        job = store.create(codes=["AAPL.US"], start_date="2026-11-12", end_date="2026-11-12", interval="1m")["id"]
        assert store.run(job)["state"] == "downloaded"
        page = store.read(job)
        assert len(page["rows"]) == 1 and page["coverage_verified"] is False and page["coverage_warning"]
    finally:
        store.close()


def test_configured_source_order_is_the_auto_baseline(monkeypatch):
    from backtest.loaders import registry

    monkeypatch.setattr(registry, "get_source_order_override", lambda market: ["yfinance", "yahoo", "stooq"])
    assert router.candidates("AAPL.US", "1m") == ["yfinance", "yahoo"]


def test_noncontinuous_minutes_keep_weekends_with_adjacent_sessions():
    plan = router.plan(["AAPL.US"], "2026-10-26", "2026-11-13", "1m", "auto")
    assert plan["parts"] == [
        ("AAPL.US", "2026-10-26", "2026-11-01"),
        ("AAPL.US", "2026-11-02", "2026-11-08"),
        ("AAPL.US", "2026-11-09", "2026-11-13"),
    ]


def test_low_frequency_history_uses_fewer_bounded_requests():
    monthly = router.plan(["AAPL.US"], "2021-11-14", "2026-11-13", "1M", "auto")
    assert monthly["chunks"] == 1 and monthly["estimated_max_rows"] == 61
    for _, start, end in monthly["parts"]:
        assert (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days < 1860
    daily = router.plan(["BTC-USDT"], "2021-11-14", "2026-11-13", "1D", "auto")
    assert daily["chunks"] == 6


def test_agent_router_plan_is_bounded_and_source_pin_is_forwarded(tmp_path, monkeypatch):
    import json
    from src.data_gateway.history_store import HistoryStore
    from src.tools.history_data_tool import HistoryDataTool

    store = HistoryStore(tmp_path)
    monkeypatch.setattr("src.data_gateway.history_store.get_history_store", lambda: store)
    try:
        reply = HistoryDataTool().execute(
            action="plan",
            codes=[f"F{i}.US" for i in range(100)],
            start_date="2026-11-02",
            end_date="2026-11-13",
            interval="1m",
            source="yahoo",
        )
        value = json.loads(reply)["data"]
        assert value["spec"]["source"] == "yahoo"
        assert value["routes_total"] == 100 and value["routes_omitted"] == 90
        assert value["spec"]["codes_total"] == 100 and len(reply) < 10000
        assert all(row["candidates"] == ["yahoo"] for row in value["routes"].values())
    finally:
        store.close()


def test_continuous_alignment_survives_legacy_metadata_and_refuses_phase_changes():
    current = {
        "source": "okx",
        "adjustment": "na",
        "quote_currency": None,
        "volume_unit": None,
        "interval": "1D",
        "bar_offset_seconds": 57600,
    }
    legacy = {
        "source": "okx",
        "adjustment": "na",
        "quote_currency": None,
        "volume_unit": None,
        "observed_start": "2025-01-01T16:00:00",
    }
    assert router._compatible(current, legacy, "crypto")
    assert not router._compatible(current | {"bar_offset_seconds": 0}, legacy, "crypto")


def test_failed_chunk_retains_first_route_evidence_after_retries(tmp_path):
    from src.data_gateway.history_store import HistoryStore

    count = 0

    def fetch(*args):
        nonlocal count
        count += 1
        raise router.HistoryRouteError(
            [{"source": "yahoo", "reason": "missing history" if count == 1 else "cooldown", "status": "unavailable"}]
        )

    store = HistoryStore(tmp_path, fetcher=fetch)
    try:
        job = store.create(codes=["AAPL.US"], start_date="2026-11-12", end_date="2026-11-12", interval="1m")["id"]
        result = store.run(job)
        assert result["state"] == "failed" and count == 3
        assert result["failure"]["routes"][0]["reason"] == "missing history"
    finally:
        store.close()


def test_pausing_a_download_stops_the_next_route_attempt(tmp_path, monkeypatch):
    from src.data_gateway.history_store import HistoryStore

    store = HistoryStore(tmp_path)
    calls = []
    job = store.create(codes=["AAPL.US"], start_date="2026-11-12", end_date="2026-11-12", interval="1m")["id"]

    def acquire(**kwargs):
        calls.append(kwargs["source"])
        store.cancel(job)
        return {"ok": False, "error": "Source unavailable"}

    monkeypatch.setattr("src.data_gateway.get_gateway", lambda: SimpleNamespace(bars=acquire, router=NetworkRouter()))
    monkeypatch.setattr(router, "candidates", lambda *args: ["first", "second"])
    try:
        result = store.run(job)
        assert result["state"] == "paused" and result["error"] is None
        assert calls == ["first"] and result["reserved"] == 0
    finally:
        store.close()


def test_boolean_prices_are_not_numeric_observations():
    rows = bars("2026-11-12", 2)
    rows[0]["close"] = True
    with pytest.raises(ValueError, match="OHLC"):
        router._normalize(rows, "AAPL.US", "2026-11-12", "2026-11-12", "5m", {"source": "yahoo"}, "us_equity")


def test_decades_are_bounded_by_chunks_and_quota_not_a_ten_year_assumption():
    value = router.plan(["AAPL.US"], "1996-11-14", "2026-11-13", "1M", "auto")
    assert value["chunks"] == 6 and value["estimated_max_rows"] == 361
    assert value["routes"]["AAPL.US"]["candidates"][0] == "yahoo"


def test_monthly_chunks_never_split_a_month_or_exceed_input_bound():
    for start in ("1996-02-29", "1996-11-14", "1996-01-01"):
        result = router.plan(["AAPL.US"], start, "2026-11-13", "1M", "auto")
        assert result["parts"][0][1] == start
        assert result["parts"][-1][2] == "2026-11-13"
        previous = None
        for _, lower, upper in result["parts"]:
            left, right = datetime.fromisoformat(lower), datetime.fromisoformat(upper)
            assert (right - left).days < 1860
            if previous:
                assert left == previous + timedelta(days=1) and left.day == 1
            previous = right


@pytest.mark.parametrize("restored", [True, False])
def test_history_observed_recovery_is_not_masked_by_negative_request_cache(tmp_path, monkeypatch, restored):
    import pandas as pd
    from backtest.loaders import registry
    from src.data_gateway.config import Config
    from src.data_gateway.service import MarketDataGateway

    registry._ensure_registered()
    calls = []
    healthy = False

    class Loader:
        name = "yahoo"

        def is_available(self):
            return True

        def fetch(self, codes, *args, **kwargs):
            calls.append(codes)
            if not healthy:
                raise ConnectionError("controlled transport outage")
            frame = pd.DataFrame(
                {k: [10.0] for k in ("open", "high", "low", "close", "volume")},
                index=pd.DatetimeIndex(["2026-11-12"], name="trade_date"),
            )
            return {code: frame for code in codes}

    monkeypatch.setitem(registry.LOADER_REGISTRY, "yahoo", Loader)
    gateway = MarketDataGateway(Config(tmp_path))
    monkeypatch.setattr("src.data_gateway.get_gateway", lambda: gateway)
    monkeypatch.setattr(router, "candidates", lambda *args: ["yahoo"])
    try:
        with pytest.raises(router.HistoryRouteError):
            router.fetch_chunk("AAPL.US", "2026-11-12", "2026-11-12", "1D")
        row = gateway.router.health[("bars:us_equity:1D", "yahoo")]
        assert row["failures"] == 1  # One network failure, not one per layer.
        assert not gateway.refresh_after
        with pytest.raises(router.HistoryRouteError):
            router.fetch_chunk("AAPL.US", "2026-11-12", "2026-11-12", "1D")
        assert len(calls) == 1  # Cooling requests generate no network traffic.
        gateway.router.record("bars:ca_equity:1D", "yahoo", True, 0.01)
        healthy = restored
        if restored:
            rows, meta = router.fetch_chunk("AAPL.US", "2026-11-12", "2026-11-12", "1D")
            assert len(rows) == 1 and meta["coverage_verified"]
        else:
            with pytest.raises(router.HistoryRouteError):
                router.fetch_chunk("AAPL.US", "2026-11-12", "2026-11-12", "1D")
            with pytest.raises(router.HistoryRouteError):
                router.fetch_chunk("AAPL.US", "2026-11-12", "2026-11-12", "1D")
            assert gateway.cache.stats()["memory_entries"] == 0
        assert len(calls) == 2  # Exactly one half-open probe, no storm.
        assert not any(scope.startswith("history:") for scope, _ in gateway.router.health)
    finally:
        gateway.close()
