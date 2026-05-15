"""SEALED baseline canary for Level 1 Market Data Routing.

Risk level: 4 (SEALED). This canary protects the public contract of the
deterministic dispatch path. Five classes:

  A. Document        — docs/MARKET_DATA_ROUTING_BASELINE.md is intact.
  B. Surface         — code modules / classes / registration are present.
  C. System prompt   — five pinned substrings survive in _SYSTEM_PROMPT.
  D. Behavioural     — three canonical interceptions + three pass-throughs.
  E. Fail-closed     — dispatcher sanitises poisoned tool errors and never
                       invokes web tools.

Failure here means a baseline regression. Investigate before merging.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_BASELINE_DOC = Path(__file__).resolve().parents[2] / "docs" / "MARKET_DATA_ROUTING_BASELINE.md"

_INVARIANT_SUBSTRINGS = (
    "Objective: deterministic pre-LLM routing of simple market-data prompts",
    "Simple market-data prompts are intercepted before the LLM/ReAct loop",
    "`market_data_router` is the deterministic entrypoint",
    "`get_market_data` is the first-class tool",
    "The LLM does not decide the first action for simple market data",
    "`web_search`, `read_url` and `browser` are forbidden as first action",
    "Inventing a skill name such as `crypto-price` is a regression",
    "Dynamic skill creation for simple market data is a regression",
    "Backtest, candlestick, strategy and swarm are not intercepted",
    "Baseline = Patch 1 + Patch 2 + Patch 3",
    "Level 1 Market Data Routing — SEALED",
)

_SECRET_SHAPED_BLOCKLIST = (
    "Authorization:", "Bearer ", "token=", "api_key=",
    "secret-", "Traceback", "internal://", "/Users/", "/home/",
    "proxy.local:",
)


# --- Class A: Document ------------------------------------------------------

@pytest.mark.unit
def test_baseline_doc_exists() -> None:
    assert _BASELINE_DOC.is_file(), (
        f"Baseline document missing at {_BASELINE_DOC}. "
        "Level 1 Market Data Routing cannot be SEALED without it."
    )


@pytest.mark.unit
def test_baseline_doc_contains_all_invariant_substrings() -> None:
    text = _BASELINE_DOC.read_text(encoding="utf-8")
    missing = [s for s in _INVARIANT_SUBSTRINGS if s not in text]
    assert not missing, f"Baseline doc is missing invariant substrings: {missing}"


@pytest.mark.unit
def test_baseline_doc_does_not_leak_secrets() -> None:
    text = _BASELINE_DOC.read_text(encoding="utf-8")
    found = [s for s in _SECRET_SHAPED_BLOCKLIST if s in text]
    assert not found, (
        f"Baseline doc contains secret-shaped substrings: {found}. "
        "Remove them; baselines must never carry credentials or stack traces."
    )


@pytest.mark.unit
def test_baseline_doc_starts_and_ends_with_sealed_marker() -> None:
    text = _BASELINE_DOC.read_text(encoding="utf-8").strip()
    marker = "Level 1 Market Data Routing — SEALED"
    assert marker in text.splitlines()[0], (
        f"First line must be the SEALED marker: '{text.splitlines()[0]}'"
    )
    assert text.endswith(marker), (
        f"Last line must be the SEALED marker: '{text.splitlines()[-1]}'"
    )


# --- Class B: Surface -------------------------------------------------------

@pytest.mark.unit
def test_module_market_data_intent_exports_detector() -> None:
    from src.agent.market_data_intent import (
        MarketDataIntent,
        detect_market_data_intent,
    )

    assert callable(detect_market_data_intent)
    assert "symbol" in MarketDataIntent.__dataclass_fields__
    assert "timeframe" in MarketDataIntent.__dataclass_fields__
    assert "limit" in MarketDataIntent.__dataclass_fields__
    assert "include_current_price" in MarketDataIntent.__dataclass_fields__


@pytest.mark.unit
def test_module_market_data_dispatcher_exports_class() -> None:
    from src.agent.market_data_dispatcher import MarketDataDispatcher

    assert MarketDataDispatcher.ROUTED_BY == "market_data_router"
    assert callable(MarketDataDispatcher().try_route)


@pytest.mark.unit
def test_get_market_data_tool_in_registry() -> None:
    from src.tools import build_registry

    registry = build_registry()
    tool = registry.get("get_market_data")
    assert tool is not None
    assert tool.name == "get_market_data"


@pytest.mark.unit
def test_loop_integrates_dispatcher() -> None:
    """The agent loop must reference MarketDataDispatcher. If someone deletes
    the integration, this canary fails before the runtime regresses."""
    from src.agent import loop as loop_module

    source = Path(loop_module.__file__).read_text(encoding="utf-8")
    assert "MarketDataDispatcher" in source, (
        "AgentLoop no longer references MarketDataDispatcher — Patch 3 "
        "integration has been removed."
    )
    assert "try_route" in source, (
        "AgentLoop no longer calls try_route — the short-circuit is broken."
    )


# --- Class C: System prompt -------------------------------------------------

@pytest.mark.unit
def test_system_prompt_pins_all_three_patches() -> None:
    from src.agent.context import _SYSTEM_PROMPT

    pins = (
        "**Market data** — user asks for",                                   # Patch 1
        "NEVER use web_search or read_url as the first action for price/OHLCV",  # Patch 1
        "web_search and read_url are FORBIDDEN for",                         # Patch 1
        "get_market_data",                                                    # Patch 2
        "routed deterministically",                                           # Patch 3
    )
    missing = [p for p in pins if p not in _SYSTEM_PROMPT]
    assert not missing, f"_SYSTEM_PROMPT lost pinned substrings: {missing}"


# --- Class D: Behavioural ---------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("prompt", [
    "Obtenha o preço atual do BTC-USDT e os últimos 7 dias de fechamento diário. Mostre como uma tabela.",
    "Get the current price of ETH-USDT and last 30 days closing prices.",
    "AAPL stock price last 5 days close",
])
def test_router_intercepts_canonical_market_prompts(prompt: str) -> None:
    from src.agent.market_data_intent import detect_market_data_intent

    intent = detect_market_data_intent(prompt)
    assert intent is not None, (
        f"Detector failed to intercept canonical market-data prompt: {prompt!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("prompt", [
    "Backtest a BTC-USDT 20/50 moving-average strategy for 2024",
    "Identify candlestick patterns on BTC-USDT last 60 days",
    "Run the crypto_research_lab swarm on ETH timeframe 30d",
])
def test_router_does_not_intercept_out_of_scope_prompts(prompt: str) -> None:
    from src.agent.market_data_intent import detect_market_data_intent

    assert detect_market_data_intent(prompt) is None, (
        f"Detector incorrectly intercepted out-of-scope prompt: {prompt!r}"
    )


# --- Class E: Fail-closed ---------------------------------------------------

def _make_registry(tool_response: str) -> MagicMock:
    reg = MagicMock()
    reg.execute = MagicMock(return_value=tool_response)
    return reg


def _trace_sink() -> tuple[MagicMock, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    trace = MagicMock()
    trace.write = MagicMock(side_effect=lambda evt: events.append(evt))
    return trace, events


@pytest.mark.unit
def test_dispatcher_failure_sanitizes_all_known_secret_substrings() -> None:
    from src.agent.market_data_dispatcher import MarketDataDispatcher

    poisoned = json.dumps({
        "status": "error",
        "error": (
            "Authorization: Bearer abc123 "
            "token=xyz api_key=APIKEY1 secret-mychain "
            "internal://proxy.local:9090/leak "
            "Traceback (most recent call last): "
            "File \"/Users/ian/secrets.py\", line 1, in <module> "
            "File \"/home/user/x.py\""
        ),
    })
    registry = _make_registry(poisoned)
    trace, _ = _trace_sink()

    result = MarketDataDispatcher().try_route(
        "BTC-USDT current price last 7 days", registry, trace,
    )

    assert result is not None
    assert result["status"] == "failed"
    content = result["content"]
    leaks = [s for s in _SECRET_SHAPED_BLOCKLIST if s in content]
    assert not leaks, (
        f"Dispatcher leaked secret-shaped substrings in error response: "
        f"{leaks!r} in content={content!r}"
    )


@pytest.mark.unit
def test_dispatcher_failure_does_not_invoke_web_tools() -> None:
    from src.agent.market_data_dispatcher import MarketDataDispatcher

    registry = _make_registry(json.dumps({"status": "error", "error": "boom"}))
    trace, _ = _trace_sink()

    MarketDataDispatcher().try_route(
        "BTC-USDT current price last 7 days", registry, trace,
    )

    invoked = [call.args[0] for call in registry.execute.call_args_list]
    assert "web_search" not in invoked
    assert "read_url" not in invoked
