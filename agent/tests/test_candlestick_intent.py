"""Unit tests for detect_candlestick_intent — deterministic detector for
candlestick analysis prompts.

Risk level 3: routes to the CandlestickWorkflowDispatcher (Patch 5).
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_intercepts_canonical_btc_usdt_en() -> None:
    from src.agent.candlestick_intent import detect_candlestick_intent

    intent = detect_candlestick_intent(
        "Analyze the candlestick patterns on BTC-USDT daily for the last 60 days. "
        "Tell me if there are any bullish or bearish signals right now."
    )
    assert intent is not None
    assert intent.symbol in ("BTC-USDT", "BTC/USDT")
    assert intent.timeframe == "1d"
    assert intent.limit == 60
    assert intent.window == 20


@pytest.mark.unit
def test_intercepts_eth_usdt_30d() -> None:
    from src.agent.candlestick_intent import detect_candlestick_intent

    intent = detect_candlestick_intent(
        "Analyze candlestick patterns on ETH-USDT last 30 days"
    )
    assert intent is not None
    assert intent.symbol in ("ETH-USDT", "ETH/USDT")
    assert intent.limit == 30


@pytest.mark.unit
def test_intercepts_pt_br() -> None:
    from src.agent.candlestick_intent import detect_candlestick_intent

    intent = detect_candlestick_intent(
        "Analise os padrões de candlestick em BTC-USDT diário nos últimos 60 dias"
    )
    assert intent is not None
    assert intent.symbol in ("BTC-USDT", "BTC/USDT")
    assert intent.limit == 60


@pytest.mark.unit
def test_default_limit_is_60() -> None:
    from src.agent.candlestick_intent import detect_candlestick_intent

    intent = detect_candlestick_intent("candlestick patterns on BTC-USDT")
    assert intent is not None
    assert intent.limit == 60


@pytest.mark.unit
def test_default_window_is_20() -> None:
    from src.agent.candlestick_intent import detect_candlestick_intent

    intent = detect_candlestick_intent("candlestick patterns on BTC-USDT")
    assert intent is not None
    assert intent.window == 20


@pytest.mark.unit
def test_limit_capped_at_200() -> None:
    from src.agent.candlestick_intent import detect_candlestick_intent

    intent = detect_candlestick_intent("candlestick BTC-USDT last 999 days")
    assert intent is not None
    assert intent.limit <= 200


# --- NEGATIVE -------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("prompt", [
    "Backtest BTC-USDT with candlestick signals as entry",
    "Build a strategy on BTC-USDT using candlestick patterns",
    "Run the crypto_research_lab swarm to analyze candlestick on ETH",
    "Optimize candlestick RSI/MACD parameters for BTC-USDT",
])
def test_does_not_intercept_blacklist(prompt: str) -> None:
    from src.agent.candlestick_intent import detect_candlestick_intent
    assert detect_candlestick_intent(prompt) is None


@pytest.mark.unit
def test_does_not_intercept_without_symbol() -> None:
    from src.agent.candlestick_intent import detect_candlestick_intent
    assert detect_candlestick_intent("How does candlestick analysis work?") is None


@pytest.mark.unit
def test_does_not_intercept_without_candlestick_word() -> None:
    from src.agent.candlestick_intent import detect_candlestick_intent
    assert detect_candlestick_intent("BTC-USDT price last 60 days") is None
