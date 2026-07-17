from __future__ import annotations

import importlib
import json

import pandas as pd
import pytest

from backtest.loaders.registry import VALID_SOURCES
from src.market_data import fetch_market_data_json
from src.swarm.models import SwarmAgentSpec
from src.swarm.presets import list_presets, load_preset
from src.swarm.worker import build_worker_prompt
from src.tools import build_swarm_registry
from src.tools.market_data_tool import MarketDataTool


def test_market_data_source_schema_matches_loader_registry():
    source_enum = MarketDataTool.parameters["properties"]["source"]["enum"]

    assert source_enum[0] == "auto"
    assert set(source_enum) == VALID_SOURCES
    assert source_enum[1:] == sorted(VALID_SOURCES - {"auto"})


def test_market_data_source_schema_does_not_resolve_loaders(monkeypatch):
    from backtest.loaders import registry as loader_registry
    from src.tools import market_data_tool

    def fail_if_called():
        pytest.fail("schema construction must not resolve or instantiate loaders")

    monkeypatch.setattr(loader_registry, "_ensure_registered", fail_if_called)
    reloaded = importlib.reload(market_data_tool)

    assert reloaded.MarketDataTool.parameters["properties"]["source"]["enum"]


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
