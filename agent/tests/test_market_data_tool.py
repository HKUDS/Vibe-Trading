from __future__ import annotations

import json

import pandas as pd

from src.market_data import fetch_market_data_json
from src.swarm.models import SwarmAgentSpec
from src.swarm.presets import list_presets, load_preset
from src.swarm.worker import build_worker_prompt
from src.tools import build_swarm_registry


def test_market_data_tool_exposes_longbridge_source():
    from src.tools.market_data_tool import MarketDataTool

    source_schema = MarketDataTool.parameters["properties"]["source"]
    assert "longbridge" in source_schema["enum"]


def test_market_data_json_accepts_explicit_longbridge_source():
    idx = pd.date_range("2026-01-01", periods=1, freq="D")
    idx.name = "trade_date"
    df = pd.DataFrame(
        {
            "open": [1.0],
            "high": [2.0],
            "low": [0.5],
            "close": [1.5],
            "volume": [100],
        },
        index=idx,
    )
    seen = []

    class _LongbridgeLoader:
        def fetch(self, codes, start, end, interval="1D"):
            seen.append((codes, start, end, interval))
            return {codes[0]: df}

    text = fetch_market_data_json(
        codes=["AAPL.US"],
        start_date="2026-01-01",
        end_date="2026-01-02",
        source="longbridge",
        loader_resolver=lambda source: _LongbridgeLoader,
    )

    payload = json.loads(text)
    assert "AAPL.US" in payload
    assert seen == [(["AAPL.US"], "2026-01-01", "2026-01-02", "1D")]


def test_market_data_json_can_include_actual_source_provenance():
    """Agent-facing payloads expose fallback/source and conversion status (#886)."""
    idx = pd.date_range("2026-01-01", periods=1, freq="D")
    idx.name = "trade_date"
    df = pd.DataFrame(
        {
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.05],
            "volume": [100],
        },
        index=idx,
    )

    class _FallbackLoader:
        def fetch(self, codes, start, end, interval="1D"):
            return {codes[0]: df}

    def _resolver(source: str):
        if source == "yahoo":
            raise RuntimeError("primary unavailable")
        return _FallbackLoader

    payload = json.loads(
        fetch_market_data_json(
            codes=["AAPL.US"],
            start_date="2026-01-01",
            end_date="2026-01-02",
            source="yahoo",
            loader_resolver=_resolver,
            fallback_chain_provider=lambda source: ["yahoo", "yfinance"],
            include_provenance=True,
        )
    )

    assert payload["_provenance"]["AAPL.US"] == {
        "source": "yfinance",
        "requested_source": "yahoo",
        "detected_source": "yahoo",
        "fallback_used": True,
        "currency_conversion": "none",
        "volume_unit": None,
        "adjustment": "split_dividend",
    }


def test_market_data_provenance_exposes_declared_volume_unit():
    """Serving loaders declare per-market volume units (#1062)."""
    idx = pd.date_range("2026-01-01", periods=1, freq="D")
    idx.name = "trade_date"
    df = pd.DataFrame(
        {
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.05],
            "volume": [100],
        },
        index=idx,
    )

    class _UnitAwareLoader:
        volume_units = {"a_share": "lots", "hk_equity": "shares"}

        def fetch(self, codes, start, end, interval="1D"):
            return {code: df for code in codes}

    payload = json.loads(
        fetch_market_data_json(
            codes=["600519.SH", "0700.HK"],
            start_date="2026-01-01",
            end_date="2026-01-02",
            source="tencent",
            loader_resolver=lambda source: _UnitAwareLoader,
            include_provenance=True,
        )
    )

    assert payload["_provenance"]["600519.SH"]["volume_unit"] == "lots"
    assert payload["_provenance"]["0700.HK"]["volume_unit"] == "shares"


def test_market_data_provenance_uses_per_symbol_currency_conversion():
    """Conversion provenance follows the frame, not the ``.L`` suffix."""
    idx = pd.date_range("2026-01-01", periods=1, freq="D")
    idx.name = "trade_date"
    df = pd.DataFrame(
        {
            "open": [1.17],
            "high": [1.18],
            "low": [1.16],
            "close": [1.175],
            "volume": [100],
        },
        index=idx,
    )

    class _UKAwareLoader:
        volume_units = {"uk_equity": "shares"}

        def fetch(self, codes, start, end, interval="1D"):
            result = {}
            for code in codes:
                frame = df.copy()
                if code == "VOD.L":
                    frame.attrs.update(
                        quote_currency="GBP",
                        currency_conversion="GBp→GBP (÷100)",
                    )
                elif code == "VUSA.L":
                    frame.attrs.update(
                        quote_currency="GBP",
                        currency_conversion="none",
                    )
                result[code] = frame
            return result

    payload = json.loads(
        fetch_market_data_json(
            codes=["VOD.L", "VUSA.L", "AAPL.US"],
            start_date="2026-01-01",
            end_date="2026-01-02",
            source="yahoo",
            loader_resolver=lambda source: _UKAwareLoader,
            include_provenance=True,
        )
    )

    assert payload["_provenance"]["VOD.L"]["currency_conversion"] == "GBp→GBP (÷100)"
    assert payload["_provenance"]["VOD.L"]["quote_currency"] == "GBP"
    assert payload["_provenance"]["VOD.L"]["volume_unit"] == "shares"
    assert payload["_provenance"]["VUSA.L"]["currency_conversion"] == "none"
    assert payload["_provenance"]["VUSA.L"]["quote_currency"] == "GBP"
    # Non-LSE symbols without frame metadata keep the neutral default.
    assert payload["_provenance"]["AAPL.US"]["currency_conversion"] == "none"


def test_market_data_provenance_volume_unit_follows_serving_loader():
    """After fallback, the unit comes from the loader that actually served."""
    idx = pd.date_range("2026-01-01", periods=1, freq="D")
    idx.name = "trade_date"
    df = pd.DataFrame(
        {
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.05],
            "volume": [100],
        },
        index=idx,
    )

    class _PrimaryLoader:
        volume_units = {"a_share": "lots"}

        def fetch(self, codes, start, end, interval="1D"):
            raise RuntimeError("primary unavailable")

    class _FallbackLoader:
        volume_units = {"a_share": "shares"}

        def fetch(self, codes, start, end, interval="1D"):
            return {codes[0]: df}

    def _resolver(source: str):
        return _PrimaryLoader if source == "tencent" else _FallbackLoader

    payload = json.loads(
        fetch_market_data_json(
            codes=["600519.SH"],
            start_date="2026-01-01",
            end_date="2026-01-02",
            source="tencent",
            loader_resolver=_resolver,
            fallback_chain_provider=lambda source: ["tencent", "baostock"],
            include_provenance=True,
        )
    )

    prov = payload["_provenance"]["600519.SH"]
    assert prov["source"] == "baostock"
    assert prov["fallback_used"] is True
    assert prov["volume_unit"] == "shares"


def test_market_data_json_is_strict_when_loader_returns_nan():

    idx = pd.date_range("2026-01-01", periods=1, freq="D")
    df = pd.DataFrame(
        {
            "open": [1.0],
            "high": [float("nan")],
            "low": [0.9],
            "close": [1.1],
            "volume": [100],
        },
        index=idx,
    )
    df.index.name = "trade_date"

    class _Loader:
        def fetch(self, codes, start, end, interval="1D"):
            return {"X.US": df}

    text = fetch_market_data_json(
        codes=["X.US"],
        start_date="2026-01-01",
        end_date="2026-01-02",
        source="yfinance",
        loader_resolver=lambda source: _Loader,
    )

    assert "NaN" not in text
    payload = json.loads(text)
    assert payload["X.US"][0]["high"] is None


def test_swarm_registry_can_expose_local_get_market_data_tool():
    registry = build_swarm_registry(["get_market_data"])

    assert "get_market_data" in registry.tool_names


def test_every_market_data_worker_has_get_market_data_tool():
    """Workers with OHLCV-capable skills must expose the loader-backed tool (#198)."""
    market_data_skills = {"tushare", "yfinance", "okx-market"}
    missing = []
    for summary in list_presets():
        preset = load_preset(summary["name"])
        for agent in preset.get("agents", []):
            if market_data_skills & set(agent.get("skills", [])):
                if "get_market_data" not in (agent.get("tools") or []):
                    missing.append(f"{summary['name']}:{agent['id']}")

    assert not missing, f"workers with market-data skills lack get_market_data: {missing}"


def test_worker_prompt_prioritizes_get_market_data_for_ohlcv():
    spec = SwarmAgentSpec(
        id="analyst",
        role="Analyst",
        system_prompt="Analyze prices.",
        tools=["load_skill", "get_market_data", "write_file"],
        skills=["yfinance"],
    )

    prompt = build_worker_prompt(spec, {}, "  - yfinance: market data")

    assert "Market Data Tool Policy" in prompt
    assert "call `get_market_data` before writing raw provider scripts" in prompt


def test_market_data_tool_rejects_empty_codes():
    from src.tools.market_data_tool import MarketDataTool

    out = json.loads(MarketDataTool().execute(codes=[], start_date="2026-01-01", end_date="2026-02-01"))
    assert out == {"ok": False, "error": "codes must be a non-empty list of strings"}


def test_market_data_tool_rejects_blank_code():
    from src.tools.market_data_tool import MarketDataTool

    out = json.loads(MarketDataTool().execute(codes=[""], start_date="2026-01-01", end_date="2026-02-01"))
    assert out == {"ok": False, "error": "every code must be a non-empty string"}


def test_market_data_tool_rejects_non_list_codes():
    from src.tools.market_data_tool import MarketDataTool

    out = json.loads(MarketDataTool().execute(codes="AAPL.US", start_date="2026-01-01", end_date="2026-02-01"))
    assert out == {"ok": False, "error": "codes must be a non-empty list of strings"}


def test_market_data_tool_rejects_missing_start_date():
    from src.tools.market_data_tool import MarketDataTool

    out = json.loads(MarketDataTool().execute(codes=["AAPL.US"], end_date="2026-02-01"))
    assert out == {"ok": False, "error": "start_date must be a non-empty YYYY-MM-DD string"}


def test_market_data_tool_rejects_malformed_dates():
    from src.tools.market_data_tool import MarketDataTool

    out = json.loads(MarketDataTool().execute(codes=["AAPL.US"], start_date="banana", end_date="2026-02-01"))
    assert out == {"ok": False, "error": "start_date and end_date must be valid YYYY-MM-DD dates"}


def test_market_data_tool_rejects_inverted_date_range():
    from src.tools.market_data_tool import MarketDataTool

    out = json.loads(MarketDataTool().execute(codes=["AAPL.US"], start_date="2026-08-21", end_date="2026-08-01"))
    assert out == {"ok": False, "error": "start_date (2026-08-21) must not be after end_date (2026-08-01)"}


def test_market_data_tool_rejects_whitespace_only_code():
    from src.tools.market_data_tool import MarketDataTool

    # Validation strips codes before the emptiness check, so a whitespace-only
    # code is caught after stripping.
    out = json.loads(MarketDataTool().execute(codes=["   "], start_date="2026-01-01", end_date="2026-02-01"))
    assert out == {"ok": False, "error": "every code must be a non-empty string"}


def test_market_data_tool_rejects_compact_date_form():
    """fromisoformat accepts YYYYMMDD on 3.11+; loaders do not. Reject it."""
    from src.tools.market_data_tool import MarketDataTool

    out = json.loads(MarketDataTool().execute(codes=["AAPL.US"], start_date="20260101", end_date="2026-02-01"))
    assert out == {"ok": False, "error": "start_date and end_date must be valid YYYY-MM-DD dates"}


def test_market_data_tool_rejects_unknown_source():
    from src.tools.market_data_tool import MarketDataTool
    from backtest.loaders.registry import VALID_SOURCES

    out = json.loads(MarketDataTool().execute(codes=["AAPL.US"], start_date="2026-01-01", end_date="2026-02-01", source="bogus"))
    assert out == {"ok": False, "error": f"source must be one of {sorted(VALID_SOURCES)}"}


def test_market_data_tool_accepts_every_registered_source():
    """Every source in the loader registry must pass MarketDataTool validation.

    Regression (#1185): the source allow-list was a hardcoded subset that
    rejected registered, documented sources (binance, local, futu, qveris,
    india_broker, tickerall). The tool's enum must match VALID_SOURCES so the
    tool can never silently drop a loader the registry serves.
    """
    import src.tools.market_data_tool as mod
    from backtest.loaders.registry import VALID_SOURCES
    from unittest import mock

    enum = set(mod.MarketDataTool.parameters["properties"]["source"]["enum"])
    assert enum == VALID_SOURCES

    calls = []
    with mock.patch.object(
        mod, "fetch_market_data_json", side_effect=lambda **kw: calls.append(kw) or "{}"
    ):
        for source in sorted(VALID_SOURCES):
            out = mod.MarketDataTool().execute(
                codes=["BTC-USDT"],
                start_date="2026-08-20",
                end_date="2026-08-21",
                source=source,
            )
            assert json.loads(out) == {}, f"source={source!r} was rejected"
    assert len(calls) == len(VALID_SOURCES)


def test_market_data_tool_rejects_garbage_interval():
    from src.tools.market_data_tool import MarketDataTool

    out = json.loads(MarketDataTool().execute(codes=["AAPL.US"], start_date="2026-01-01", end_date="2026-02-01", interval="BANANA"))
    assert out["ok"] is False
    assert "interval must be one of" in out["error"]
    assert "BANANA" in out["error"]


def test_market_data_tool_normalizes_interval_case():
    """'1d' is accepted but normalized to canonical '1D' before fetch."""
    import src.tools.market_data_tool as mod
    from unittest import mock

    calls = []
    with mock.patch.object(mod, "fetch_market_data_json", side_effect=lambda **kw: calls.append(kw) or "{}"):
        mod.MarketDataTool().execute(codes=["AAPL.US"], start_date="2026-08-20", end_date="2026-08-21", interval="1d", max_rows=0)
    assert calls and calls[0]["interval"] == "1D"


def test_market_data_tool_rejects_non_int_max_rows():
    from src.tools.market_data_tool import MarketDataTool

    out = json.loads(MarketDataTool().execute(codes=["AAPL.US"], start_date="2026-01-01", end_date="2026-02-01", max_rows="abc"))
    assert out == {"ok": False, "error": "max_rows must be a non-negative integer (0 = all rows)"}


def test_market_data_tool_clamps_negative_max_rows_to_default_cap():
    """Negative max_rows is invalid but must never be unbounded (P07 G3ii):
    it is clamped to the default cap before fetching, same as cap_rows."""
    import src.tools.market_data_tool as mod
    from unittest import mock

    calls = []
    with mock.patch.object(mod, "fetch_market_data_json", side_effect=lambda **kw: calls.append(kw) or "{}"):
        out = mod.MarketDataTool().execute(
            codes=["AAPL.US"], start_date="2026-08-20", end_date="2026-08-21", max_rows=-5
        )
    assert json.loads(out) == {}
    assert calls and calls[0]["max_rows"] == mod.DEFAULT_MAX_ROWS


def test_market_data_tool_accepts_minute_intervals():
    """'30m' is documented-valid; '30M' must normalize to it, not to '30M'.

    Regression: plain .upper() turned valid minute intervals ('1m', '5m',
    '15m', '30m') into '1M'/'30M' which are not in _VALID_INTERVALS.
    """
    import src.tools.market_data_tool as mod
    from unittest import mock

    calls = []
    with mock.patch.object(mod, "fetch_market_data_json", side_effect=lambda **kw: calls.append(kw) or "{}"):
        for interval in ("1m", "5m", "15m", "30m", "30M", "1H", "1d"):
            out = mod.MarketDataTool().execute(
                codes=["AAPL.US"],
                start_date="2026-08-20",
                end_date="2026-08-21",
                interval=interval,
            )
            assert json.loads(out) == {}
    assert [c["interval"] for c in calls] == ["1m", "5m", "15m", "30m", "30m", "1H", "1D"]
