"""Offline contracts for current HK quote identity, timing and fallback."""

from __future__ import annotations

import json
import contextlib
import io
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import requests

from src.hk_data import service
from src.tools import hk_quotes_tool

UTC = timezone.utc
NOW = datetime(2026, 11, 11, 7, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unit tests must not reach a provider")

    monkeypatch.setattr(service, "throttled_get", blocked)
    monkeypatch.setattr(service, "throttled_get_json", blocked)


@pytest.fixture
def fixed_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(service, "datetime", Clock)


def quote(symbol="00700.HK", source="yahoo", age=60, price=400):
    return service._quote(
        symbol,
        source,
        price,
        NOW - timedelta(seconds=age),
        NOW,
        currency="HKD",
    )


def yahoo_payload(**meta_overrides):
    meta = {
        "symbol": "0700.HK",
        "regularMarketPrice": 400.5,
        "regularMarketTime": int((NOW - timedelta(seconds=900)).timestamp()),
        "currency": "HKD",
        "regularMarketVolume": 12345,
    }
    meta.update(meta_overrides)
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": meta,
                    "timestamp": [int((NOW - timedelta(seconds=30)).timestamp())],
                    "indicators": {"quote": [{"close": [999.0]}]},
                }
            ],
        }
    }


def tencent_row(code="00700", timestamp="2026/11/11 15:00:00", price="400.5"):
    parts = [""] * 50
    parts[2], parts[3], parts[30] = code, price, timestamp
    return f'v_hk{code}="{"~".join(parts)}";'


def response(text):
    return SimpleNamespace(text=text, encoding=None, raise_for_status=lambda: None)


@pytest.mark.parametrize(
    "value", ["700", "0700.HK", "00700.HK", "HK.00700", " hk.700 "]
)
def test_symbol_aliases_normalize_to_same_security(value):
    assert service.normalize_symbol(value) == "00700.HK"


@pytest.mark.parametrize(
    "value",
    [
        "0",
        "00000.HK",
        "AAPL.US",
        "600519.SH",
        "^HSI",
        "0700.HK?q=5",
        "../700",
        "700,5",
        "HK.700.HK",
        "100000.HK",
        "",
        None,
        700,
    ],
)
def test_invalid_foreign_or_injected_symbol_is_rejected(value):
    with pytest.raises(ValueError):
        service.normalize_symbol(value)


def test_aliases_deduplicate_without_collapsing_currency_counters():
    assert service.normalize_symbols(
        ["700", "0700.HK", "80700.HK", "03081.HK", "09081.HK"]
    ) == [
        "00700.HK",
        "80700.HK",
        "03081.HK",
        "09081.HK",
    ]


@pytest.mark.parametrize("values", [[], "700", None, ["700"] * 101])
def test_invalid_batch_rejected(values):
    with pytest.raises(ValueError):
        service.normalize_symbols(values)


def test_yahoo_uses_paired_metadata_price_and_time_not_latest_bar(
    monkeypatch, fixed_clock
):
    seen = []

    def fetch(url, **kwargs):
        seen.append((url, kwargs))
        return yahoo_payload()

    monkeypatch.setattr(service, "throttled_get_json", fetch)
    result = service._yahoo("00700.HK", NOW)
    assert result["price"] == 400.5
    assert result["provider_time"] == "2026-11-11T06:45:00.000+00:00"
    assert result["observed_at_utc"] == "2026-11-11T07:00:00.000+00:00"
    assert result["currency"] == "HKD"
    assert result["volume"] == 12345
    assert result["volume_scope"] == "session_cumulative"
    assert result["declared_delay_seconds"] == 900
    assert result["delay_status"] == "delayed"
    assert seen[0][0].endswith("/0700.HK")
    assert seen[0][1]["host_key"] == "yahoo"


@pytest.mark.parametrize(
    "missing", ["regularMarketTime", "regularMarketPrice", "currency"]
)
def test_yahoo_missing_required_fields_do_not_fabricate_quote(
    monkeypatch, fixed_clock, missing
):
    payload = yahoo_payload()
    del payload["chart"]["result"][0]["meta"][missing]
    monkeypatch.setattr(service, "throttled_get_json", lambda *args, **kwargs: payload)
    result = service.fetch_quotes(["700"], source="yahoo")
    assert result["ok"] is False
    assert result["quotes"] == []
    assert result["missing"] == ["00700.HK"]


@pytest.mark.parametrize("bad_price", [float("nan"), float("inf"), -1, 0, True])
def test_yahoo_invalid_prices_are_unavailable(monkeypatch, fixed_clock, bad_price):
    monkeypatch.setattr(
        service,
        "throttled_get_json",
        lambda *args, **kwargs: yahoo_payload(regularMarketPrice=bad_price),
    )
    result = service.fetch_quotes(["700"], source="yahoo")
    assert result["quotes"] == []
    json.dumps(result, allow_nan=False)


def test_yahoo_foreign_returned_identity_cannot_be_used(monkeypatch, fixed_clock):
    monkeypatch.setattr(
        service,
        "throttled_get_json",
        lambda *args, **kwargs: yahoo_payload(symbol="AAPL"),
    )
    result = service.fetch_quotes(["700"], source="yahoo")
    assert result["quotes"] == []


def test_yahoo_currency_is_provider_declared(monkeypatch):
    monkeypatch.setattr(
        service,
        "throttled_get_json",
        lambda *args, **kwargs: yahoo_payload(symbol="80700.HK", currency="CNY"),
    )
    assert service._yahoo("80700.HK", NOW)["currency"] == "CNY"


@pytest.mark.parametrize(
    "timestamp", ["2026/11/11 15:00:00", "2026-11-11 15:00:00", "20261111150000"]
)
def test_tencent_supported_timestamp_formats_are_hong_kong_time(monkeypatch, timestamp):
    monkeypatch.setattr(
        service,
        "throttled_get",
        lambda *args, **kwargs: response(tencent_row(timestamp=timestamp)),
    )
    quotes, errors = service._tencent(["00700.HK"], NOW)
    assert errors == []
    assert len(quotes) == 1
    assert quotes[0]["provider_time"] == "2026-11-11T07:00:00.000+00:00"
    assert quotes[0]["price"] == 400.5
    assert quotes[0]["volume"] is None
    assert quotes[0]["volume_unit"] is None
    assert quotes[0]["delay_status"] == "unknown"


def test_tencent_counter_currency_and_partial_failures(monkeypatch):
    text = "\n".join(tencent_row(code=code) for code in ["00700", "80700", "09081"])
    monkeypatch.setattr(
        service, "throttled_get", lambda *args, **kwargs: response(text)
    )
    quotes, errors = service._tencent(
        ["00700.HK", "80700.HK", "09081.HK", "00005.HK"], NOW
    )
    assert {row["symbol"]: row["currency"] for row in quotes} == {
        "00700.HK": "HKD",
        "80700.HK": "CNY",
        "09081.HK": "USD",
    }
    assert [item["symbol"] for item in errors] == ["00005.HK"]


@pytest.mark.parametrize("timestamp", ["", "2026/13/11 15:00:00", "junk"])
def test_tencent_invalid_time_never_becomes_observation_time(monkeypatch, timestamp):
    monkeypatch.setattr(
        service,
        "throttled_get",
        lambda *args, **kwargs: response(tencent_row(timestamp=timestamp)),
    )
    quotes, errors = service._tencent(["00700.HK"], NOW)
    assert quotes == []
    assert errors[0]["symbol"] == "00700.HK"


def test_future_provider_time_is_rejected(monkeypatch, fixed_clock):
    monkeypatch.setattr(service, "_yahoo", lambda *args: quote(age=-30))
    result = service.fetch_quotes(["700"], source="yahoo")
    assert result["quotes"] == []
    assert result["errors"][0]["error"] == "ValueError"


def test_stale_yahoo_triggers_fallback_but_newest_quote_wins(monkeypatch, fixed_clock):
    called = []
    monkeypatch.setattr(service, "_yahoo", lambda symbol, now: quote(symbol, age=1500))

    def tencent(symbols, now):
        called.extend(symbols)
        return [
            quote("00700.HK", "tencent", age=30),
            quote("00005.HK", "tencent", age=2000),
        ], []

    monkeypatch.setattr(service, "_tencent", tencent)
    result = service.fetch_quotes(["700", "5"], max_age_seconds=1200)
    rows = {row["symbol"]: row for row in result["quotes"]}
    assert called == ["00700.HK", "00005.HK"]
    assert rows["00700.HK"]["source"] == "tencent"
    assert rows["00700.HK"]["status"] == "fresh"
    assert rows["00005.HK"]["source"] == "yahoo"
    assert rows["00005.HK"]["status"] == "stale"


def test_fresh_yahoo_does_not_trigger_fallback(monkeypatch, fixed_clock):
    monkeypatch.setattr(service, "_yahoo", lambda symbol, now: quote(symbol))
    monkeypatch.setattr(
        service, "_tencent", lambda *args: pytest.fail("Unexpected fallback")
    )
    result = service.fetch_quotes(["700"])
    assert result["quotes"][0]["source"] == "yahoo"


@pytest.mark.parametrize("source", ["yahoo", "tencent", "futu"])
def test_explicit_source_never_uses_other_providers(monkeypatch, fixed_clock, source):
    def wrong(*args):
        pytest.fail("Explicit provider selection was not respected")

    for provider in ["yahoo", "tencent", "futu"]:
        monkeypatch.setattr(service, "_" + provider, wrong)
    if source == "yahoo":
        monkeypatch.setattr(
            service, "_yahoo", lambda symbol, now: quote(symbol, source, age=3000)
        )
    else:
        monkeypatch.setattr(
            service,
            "_" + source,
            lambda symbols, now: ([quote(symbols[0], source, age=3000)], []),
        )
    result = service.fetch_quotes(["700"], source=source)
    assert result["quotes"][0]["source"] == source
    assert result["quotes"][0]["status"] == "stale"


def test_provider_failure_preserves_other_symbols_and_sanitizes_error(
    monkeypatch, fixed_clock
):
    def yahoo(symbol, now):
        if symbol == "00005.HK":
            raise RuntimeError("private-token-account-path")
        return quote(symbol)

    monkeypatch.setattr(service, "_yahoo", yahoo)
    result = service.fetch_quotes(["700", "5"], source="yahoo")
    assert result["ok"] is True
    assert result["status"] == "partial"
    assert [row["symbol"] for row in result["quotes"]] == ["00700.HK"]
    assert result["missing"] == ["00005.HK"]
    assert "private-token" not in json.dumps(result)


def test_cached_quote_age_recomputed_without_mutating_original_time():
    original = quote(age=60)
    fresh = service.quote_age(original, NOW, 120)
    stale = service.quote_age(fresh, NOW + timedelta(minutes=5), 120)
    assert fresh["status"] == "fresh"
    assert stale["status"] == "stale"
    assert stale["age_seconds"] == 360
    assert stale["provider_time"] == original["provider_time"]
    assert stale["observed_at_utc"] == original["observed_at_utc"]
    assert "status" not in original


@pytest.mark.parametrize("age", [0, -1, float("nan"), float("inf"), True, "1200"])
def test_invalid_max_age_is_rejected(age):
    with pytest.raises(ValueError):
        service.fetch_quotes(["700"], max_age_seconds=age)


def test_yahoo_circuit_breaker_bounds_network_outage_and_fallback_recovers(
    monkeypatch, fixed_clock
):
    called = []

    def failed(symbol, now):
        called.append(symbol)
        raise requests.Timeout("private-network-diagnostic")

    monkeypatch.setattr(service, "_yahoo", failed)
    monkeypatch.setattr(
        service,
        "_tencent",
        lambda symbols, now: ([quote(symbol, "tencent") for symbol in symbols], []),
    )
    result = service.fetch_quotes(["700", "5", "388", "941", "1299"])
    assert len(called) == 3
    assert len(result["quotes"]) == 5
    assert {item["source"] for item in result["quotes"]} == {"tencent"}
    assert [error["error"] for error in result["errors"]] == [
        "Timeout",
        "Timeout",
        "Timeout",
        "ProviderUnavailable",
        "ProviderUnavailable",
    ]
    assert "private-network" not in json.dumps(result)


def test_yahoo_parse_failures_do_not_short_circuit_valid_later_symbols(
    monkeypatch, fixed_clock
):
    called = []

    def parsed(symbol, now):
        called.append(symbol)
        if symbol != "01299.HK":
            raise ValueError("Missing metadata")
        return quote(symbol)

    monkeypatch.setattr(service, "_yahoo", parsed)
    result = service.fetch_quotes(["700", "5", "388", "941", "1299"], source="yahoo")
    assert len(called) == 5
    assert [row["symbol"] for row in result["quotes"]] == ["01299.HK"]


def test_futu_worker_is_quote_only_closes_context_and_batches_bmp_limit(
    monkeypatch, capsys
):
    from src.hk_data import futu_worker

    calls = []
    closed = []

    class Frame:
        def __init__(self, codes):
            self.codes = codes

        def to_dict(self, orientation):
            assert orientation == "records"
            return [
                {
                    "code": code,
                    "update_time": "2026-11-11 15:00:00",
                    "last_price": 10,
                    "volume": 100,
                }
                for code in self.codes
            ]

    class Context:
        def get_market_snapshot(self, codes):
            calls.append(codes)
            return 0, Frame(codes)

        def close(self):
            closed.append(True)

    monkeypatch.setitem(
        sys.modules,
        "futu",
        SimpleNamespace(RET_OK=0, OpenQuoteContext=lambda **kwargs: Context()),
    )
    symbols = [f"{number:05d}.HK" for number in range(1, 24)]
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(symbols)))
    assert futu_worker.main() == 0
    rows = json.loads(capsys.readouterr().out)["rows"]
    assert len(rows) == 23
    assert [len(batch) for batch in calls] == [20, 3]
    assert closed == [True]
    assert rows[0]["update_time"] == "2026-11-11 15:00:00"


def test_futu_worker_timeout_becomes_sanitized_unavailable_quotes(
    monkeypatch, fixed_clock
):
    monkeypatch.setattr(
        service.socket,
        "create_connection",
        lambda *args, **kwargs: contextlib.nullcontext(),
    )
    calls = []

    def timed_out(command, **kwargs):
        calls.append((command, kwargs))
        raise subprocess.TimeoutExpired(
            command, timeout=20, stderr="private-futu-login"
        )

    monkeypatch.setattr(service.subprocess, "run", timed_out)
    result = service.fetch_quotes(["700", "5"], source="futu")
    assert result["ok"] is False
    assert result["quotes"] == []
    assert result["missing"] == ["00700.HK", "00005.HK"]
    assert len(result["errors"]) == 2
    assert {error["error"] for error in result["errors"]} == {"TimeoutExpired"}
    assert calls[0][1]["timeout"] == 20
    assert calls[0][0][1:] == ["-m", "src.hk_data.futu_worker"]
    assert "private-futu" not in json.dumps(result)


def test_futu_worker_result_parses_hk_time_and_quote_currency(monkeypatch, fixed_clock):
    monkeypatch.setattr(
        service.socket,
        "create_connection",
        lambda *args, **kwargs: contextlib.nullcontext(),
    )
    rows = [
        {
            "code": "HK.80700",
            "last_price": "350",
            "update_time": "2026-11-11 15:00:00",
            "volume": "100",
        }
    ]
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps({"rows": rows})),
    )
    result = service.fetch_quotes(["80700"], source="futu")
    assert result["quotes"][0]["provider_time"] == "2026-11-11T07:00:00.000+00:00"
    assert result["quotes"][0]["currency"] == "CNY"
    assert result["quotes"][0]["volume"] == 100


def test_tool_errors_are_strict_json_and_repeatable():
    tool = hk_quotes_tool.HKQuotesTool()
    assert tool.repeatable is True
    assert tool.is_readonly is True
    result = json.loads(tool.execute(symbols=["AAPL.US"]))
    assert result["ok"] is False
    assert result["status"] == "error"
    assert "Hong Kong" in result["error"]


def test_tool_forwards_source_and_freshness(monkeypatch):
    called = []

    def fetch(symbols, source, age):
        called.append((symbols, source, age))
        return {"ok": True, "quotes": [quote()]}

    monkeypatch.setattr(hk_quotes_tool, "fetch_quotes", fetch)
    value = hk_quotes_tool.HKQuotesTool().execute(
        symbols=["700"], source="tencent", max_age_seconds=300
    )
    assert json.loads(value)["ok"] is True
    assert called == [(["700"], "tencent", 300)]


def test_tool_defaults_to_fast_endpoint_and_one_minute_freshness(monkeypatch):
    called = []

    def fetch(symbols, source, age):
        called.append((symbols, source, age))
        return {"ok": True, "quotes": []}

    monkeypatch.setattr(hk_quotes_tool, "fetch_quotes", fetch)
    hk_quotes_tool.HKQuotesTool().execute(symbols=["700"])
    assert called == [(["700"], "tencent", 60)]
