"""Unit tests for CandlestickWorkflowDispatcher (Patch 5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


def _trace_sink() -> tuple[MagicMock, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    trace = MagicMock()
    trace.write = MagicMock(side_effect=lambda evt: events.append(evt))
    return trace, events


def _ohlcv_ok(symbol: str = "BTC/USDT", n: int = 60) -> str:
    from datetime import datetime, timedelta, timezone
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    candles = [
        {
            "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            "open": 80000 + i, "high": 80500 + i, "low": 79500 + i,
            "close": 80200 + i, "volume": 1000.0 + i,
        }
        for i in range(n)
    ]
    return json.dumps({
        "status": "ok", "symbol": symbol, "provider": "ccxt",
        "timeframe": "1d", "current_price": candles[-1]["close"],
        "candles": candles,
    })


def _pattern_response(bull: int, bear: int, neutral: int, code: str = "BTC_USDT") -> str:
    counts: dict = {}
    if bull: counts[1] = bull
    if bear: counts[-1] = bear
    if neutral: counts[0] = neutral
    return json.dumps({
        "status": "ok",
        "results": {code: {"candlestick": counts}},
        "patterns": ["candlestick"], "window": 20,
    })


def _registry(get_md_response: str, pattern_response: str) -> MagicMock:
    reg = MagicMock()

    def _execute(name: str, args: dict) -> str:
        if name == "get_market_data":
            return get_md_response
        if name == "pattern":
            return pattern_response
        return json.dumps({"status": "error", "error": f"unknown tool {name}"})

    reg.execute = MagicMock(side_effect=_execute)
    return reg


@pytest.mark.unit
def test_workflow_returns_none_for_non_candlestick_prompt(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    reg = _registry(_ohlcv_ok(), _pattern_response(1, 0, 30))
    trace, _ = _trace_sink()
    result = CandlestickWorkflowDispatcher().try_route(
        "Backtest BTC-USDT 20/50 moving-average for 2024", reg, trace, str(tmp_path),
    )
    assert result is None
    reg.execute.assert_not_called()


@pytest.mark.unit
def test_workflow_calls_get_market_data_before_pattern(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    reg = _registry(_ohlcv_ok(), _pattern_response(5, 1, 50))
    trace, _ = _trace_sink()
    result = CandlestickWorkflowDispatcher().try_route(
        "Analyze candlestick patterns on BTC-USDT daily for the last 60 days",
        reg, trace, str(tmp_path),
    )
    assert result is not None
    assert result["status"] == "success"

    names_in_order = [c.args[0] for c in reg.execute.call_args_list]
    assert names_in_order[0] == "get_market_data", names_in_order
    assert "pattern" in names_in_order
    assert names_in_order.index("get_market_data") < names_in_order.index("pattern")


@pytest.mark.unit
def test_workflow_passes_real_run_dir_to_pattern(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    reg = _registry(_ohlcv_ok(), _pattern_response(1, 0, 0))
    trace, _ = _trace_sink()
    CandlestickWorkflowDispatcher().try_route(
        "Analyze candlestick patterns on BTC-USDT last 60 days",
        reg, trace, str(tmp_path),
    )
    pattern_call = next(c for c in reg.execute.call_args_list if c.args[0] == "pattern")
    pattern_args = pattern_call.args[1]
    assert pattern_args["run_dir"] == str(tmp_path)
    assert "patterns" in pattern_args


@pytest.mark.unit
def test_workflow_persists_ohlcv_in_run_dir_artifacts(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    reg = _registry(_ohlcv_ok(), _pattern_response(1, 0, 0))
    trace, _ = _trace_sink()
    CandlestickWorkflowDispatcher().try_route(
        "candlestick on BTC-USDT", reg, trace, str(tmp_path),
    )
    csv = tmp_path / "artifacts" / "ohlcv_BTC_USDT.csv"
    assert csv.is_file(), f"OHLCV CSV not written: {list((tmp_path / 'artifacts').glob('*')) if (tmp_path / 'artifacts').exists() else 'no artifacts/'}"
    text = csv.read_text()
    assert "open" in text.lower()
    assert "close" in text.lower()


@pytest.mark.unit
@pytest.mark.parametrize("bull,bear,neutral,expected", [
    (10, 1, 30, "bullish"),
    (1, 10, 30, "bearish"),
    (0, 0, 30, "no_clear_signal"),
    (2, 2, 30, "neutral"),
    (5, 3, 30, "neutral"),
])
def test_workflow_verdict_mapping(tmp_path: Path, bull: int, bear: int,
                                  neutral: int, expected: str) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    reg = _registry(_ohlcv_ok(), _pattern_response(bull, bear, neutral))
    trace, _ = _trace_sink()
    result = CandlestickWorkflowDispatcher().try_route(
        "candlestick on BTC-USDT", reg, trace, str(tmp_path),
    )
    assert result is not None
    assert result.get("verdict") == expected, (
        f"bull={bull} bear={bear} neutral={neutral} → expected {expected}, "
        f"got {result.get('verdict')}"
    )
    assert expected in result["content"].lower()


@pytest.mark.unit
def test_workflow_get_market_data_failure_is_fail_closed(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    bad = json.dumps({
        "status": "error",
        "error": "Authorization: Bearer secret-xyz Traceback /Users/ian internal://proxy.local:9090",
    })
    reg = _registry(bad, _pattern_response(0, 0, 0))
    trace, _ = _trace_sink()
    result = CandlestickWorkflowDispatcher().try_route(
        "candlestick on BTC-USDT", reg, trace, str(tmp_path),
    )
    assert result is not None
    assert result["status"] == "failed"
    pattern_calls = [c for c in reg.execute.call_args_list if c.args[0] == "pattern"]
    assert not pattern_calls, "Pattern must NOT be called when get_market_data fails."

    for forbidden in ("Authorization", "Bearer ", "secret-", "Traceback",
                      "/Users/", "internal://", "proxy.local:"):
        assert forbidden not in result["content"], (
            f"Leaked {forbidden!r} into failure response: {result['content']!r}"
        )


@pytest.mark.unit
def test_workflow_pattern_failure_is_fail_closed(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    bad_pattern = json.dumps({
        "status": "error",
        "error": "Bearer token=abc /home/x proxy.local:5050 secret-y Traceback",
    })
    reg = _registry(_ohlcv_ok(), bad_pattern)
    trace, _ = _trace_sink()
    result = CandlestickWorkflowDispatcher().try_route(
        "candlestick on BTC-USDT", reg, trace, str(tmp_path),
    )
    assert result is not None
    assert result["status"] == "failed"
    for forbidden in ("Bearer ", "token=", "/home/", "proxy.local:", "secret-", "Traceback"):
        assert forbidden not in result["content"]


@pytest.mark.unit
def test_workflow_never_invokes_web_tools(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    reg = _registry(_ohlcv_ok(), _pattern_response(1, 0, 0))
    trace, _ = _trace_sink()
    CandlestickWorkflowDispatcher().try_route(
        "candlestick on BTC-USDT", reg, trace, str(tmp_path),
    )
    names = [c.args[0] for c in reg.execute.call_args_list]
    assert "web_search" not in names
    assert "read_url" not in names


@pytest.mark.unit
def test_workflow_emits_trace_events_in_order(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    reg = _registry(_ohlcv_ok(), _pattern_response(2, 1, 30))
    trace, events = _trace_sink()
    CandlestickWorkflowDispatcher().try_route(
        "candlestick on BTC-USDT", reg, trace, str(tmp_path),
    )
    types = [e.get("type") for e in events]
    assert "router" in types
    tool_call_names = [e.get("name") for e in events if e.get("type") == "tool_call"]
    assert "get_market_data" in tool_call_names
    assert "pattern" in tool_call_names
    assert tool_call_names.index("get_market_data") < tool_call_names.index("pattern")
    assert any(e.get("type") == "workflow_step" and e.get("name") == "persist_ohlcv"
               for e in events)
    ends = [e for e in events if e.get("type") == "end"]
    assert ends and ends[-1].get("routed_by") == "candlestick_workflow"
    assert ends[-1].get("iterations") == 0
