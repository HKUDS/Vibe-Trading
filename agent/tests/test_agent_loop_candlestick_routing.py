"""Integration tests for the candlestick short-circuit in AgentLoop (Patch 5).

Confirms:
- canonical candlestick prompt: llm.stream_chat NOT called, routed_by =
  candlestick_workflow, iterations=0
- market-data prompt: short-circuits via market_data_router (Patch 3 intact)
- backtest prompt: normal ReAct loop runs (LLM called >= 1 time)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _build_loop(tmp_path: Path, llm: MagicMock):
    from src.agent.loop import AgentLoop
    from src.agent.memory import WorkspaceMemory
    from src.agent.tools import ToolRegistry

    registry = ToolRegistry()

    # Fake get_market_data
    md = MagicMock()
    md.name = "get_market_data"
    md.repeatable = True
    md.is_readonly = True
    md.execute = MagicMock(return_value=json.dumps({
        "status": "ok", "symbol": "BTC/USDT", "provider": "ccxt",
        "timeframe": "1d", "current_price": 80000.0,
        "candles": [
            {"date": "2026-03-01", "open": 80000, "high": 80500,
             "low": 79500, "close": 80200, "volume": 1000.0},
        ] * 60,
    }))
    registry.register(md)

    # Fake pattern
    pt = MagicMock()
    pt.name = "pattern"
    pt.repeatable = True
    pt.is_readonly = True
    pt.execute = MagicMock(return_value=json.dumps({
        "status": "ok",
        "results": {"BTC_USDT": {"candlestick": {1: 5, -1: 1, 0: 50}}},
        "patterns": ["candlestick"], "window": 20,
    }))
    registry.register(pt)

    memory = WorkspaceMemory(run_dir=str(tmp_path))
    return AgentLoop(llm=llm, registry=registry, memory=memory)


@pytest.mark.unit
def test_loop_does_not_call_llm_for_candlestick_prompt(tmp_path: Path) -> None:
    llm = MagicMock()
    llm.stream_chat = MagicMock()
    llm.chat = MagicMock()
    loop = _build_loop(tmp_path, llm)

    result = loop.run(
        "Analyze the candlestick patterns on BTC-USDT daily for the last 60 days. "
        "Tell me if there are any bullish or bearish signals right now."
    )

    assert llm.stream_chat.call_count == 0, (
        f"LLM was invoked {llm.stream_chat.call_count} times — Patch 5 "
        "should short-circuit before the ReAct loop."
    )
    assert result.get("iterations") == 0
    assert result.get("routed_by") == "candlestick_workflow"
    assert result.get("status") in ("success", "ok")
    assert result.get("verdict") in {"bullish", "bearish", "neutral", "no_clear_signal"}


@pytest.mark.unit
def test_loop_still_short_circuits_simple_market_data_prompt(tmp_path: Path) -> None:
    """Anti-regression: Patch 3's market_data_router must still win for
    simple price/OHLCV prompts (Patch 5 must not steal them)."""
    llm = MagicMock()
    llm.stream_chat = MagicMock()
    llm.chat = MagicMock()
    loop = _build_loop(tmp_path, llm)

    result = loop.run(
        "Obtenha o preço atual do BTC-USDT e os últimos 7 dias de fechamento "
        "diário. Mostre como uma tabela."
    )
    assert result.get("routed_by") == "market_data_router", (
        f"Patch 3 regression — got routed_by={result.get('routed_by')}"
    )


@pytest.mark.unit
def test_loop_invokes_llm_for_backtest_prompt(tmp_path: Path) -> None:
    """Anti-regression: backtest prompts must reach the ReAct loop."""
    from src.providers.chat import LLMResponse

    llm = MagicMock()
    llm.stream_chat = MagicMock(return_value=LLMResponse(
        content="ok", tool_calls=[], finish_reason="stop"
    ))
    llm.chat = MagicMock(return_value=LLMResponse(
        content="ok", tool_calls=[], finish_reason="stop"
    ))
    loop = _build_loop(tmp_path, llm)

    result = loop.run("Backtest a BTC-USDT 20/50 moving-average strategy for 2024")

    assert llm.stream_chat.call_count >= 1
    assert result.get("routed_by") not in ("candlestick_workflow", "market_data_router")
