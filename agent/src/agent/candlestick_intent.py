"""Deterministic detector for simple candlestick-pattern analysis prompts.

Returns a CandlestickIntent only when the prompt clearly asks for candlestick
analysis on a known symbol AND does not look like a backtest/strategy/swarm
request. Used by CandlestickWorkflowDispatcher (Patch 5) to short-circuit
the ReAct loop with a deterministic workflow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from src.agent.market_data_intent import _extract_symbol

_CANDLESTICK_WORDS = (
    "candlestick", "candlesticks",
    "padrões de candle", "padrao de candle", "padrões de candlestick",
)

_BLACKLIST = (
    "backtest",
    "strategy", "estratégia", "estrategia",
    "swarm", "signal_engine", "signal engine",
    "optimize", "otimizar",
    "moving average", "média móvel", "media movel",
    "rsi", "macd",
    "entry signal", "entry signals",
)

_LIMIT_RE = re.compile(r"\b(\d{1,3})\s*(?:days?|dias?)\b", re.IGNORECASE)
_WINDOW_RE = re.compile(r"\bwindow\s*=?\s*(\d+)\b", re.IGNORECASE)
_TIMEFRAME_HOUR_RE = re.compile(r"\b(?:hour(?:ly)?|hora|horár)", re.IGNORECASE)
_TIMEFRAME_15M_RE = re.compile(r"\b(?:15\s*-?\s*(?:m|min|minute|minutos?))\b", re.IGNORECASE)


@dataclass(frozen=True)
class CandlestickIntent:
    """Structured result of a successful candlestick-analysis intent."""
    symbol: str
    timeframe: str
    limit: int
    window: int


def _has_candlestick_word(prompt_lower: str) -> bool:
    return any(w in prompt_lower for w in _CANDLESTICK_WORDS)


def _matches_blacklist(prompt_lower: str) -> bool:
    return any(tok in prompt_lower for tok in _BLACKLIST)


def _extract_limit(prompt: str) -> int:
    m = _LIMIT_RE.search(prompt)
    if m:
        return min(int(m.group(1)), 200)
    return 60


def _extract_window(prompt: str) -> int:
    m = _WINDOW_RE.search(prompt)
    if m:
        return min(int(m.group(1)), 200)
    return 20


def _extract_timeframe(prompt: str) -> str:
    if _TIMEFRAME_15M_RE.search(prompt):
        return "15m"
    if _TIMEFRAME_HOUR_RE.search(prompt):
        return "1h"
    return "1d"


def detect_candlestick_intent(prompt: str) -> Optional[CandlestickIntent]:
    if not prompt or not isinstance(prompt, str):
        return None

    prompt_lower = prompt.lower()
    if _matches_blacklist(prompt_lower):
        return None
    if not _has_candlestick_word(prompt_lower):
        return None

    symbol = _extract_symbol(prompt)
    if symbol is None:
        return None

    return CandlestickIntent(
        symbol=symbol,
        timeframe=_extract_timeframe(prompt),
        limit=_extract_limit(prompt),
        window=_extract_window(prompt),
    )
