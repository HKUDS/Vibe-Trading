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
    }


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
