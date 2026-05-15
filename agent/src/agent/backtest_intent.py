"""Deterministic detector for simple MA-crossover backtest prompts."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from src.agent.market_data_intent import _extract_symbol

_BACKTEST_WORDS = ("backtest",)
_MA_WORDS = (
    "moving average", "moving-average",
    "média móvel", "media movel",
)
_CROSSOVER_WORDS = (
    "crossover", "crosses above", "crosses below",
    "cross above", "cross below",
)
_BLACKLIST = (
    "candlestick pattern", "candlestick patterns",
    "padrões de candle", "padrao de candle",
    "swarm", "rsi", "macd", "bollinger", "ichimoku",
    "options strategy", "options portfolio",
)

_WINDOW_NAMED_RE = re.compile(
    r"\b(\d{1,3})[- ]day[s]?\s+(?:MA|SMA|EMA|moving[- ]average)\b",
    re.IGNORECASE,
)
_WINDOW_SLASH_RE = re.compile(
    r"\b(\d{1,3})\s*/\s*(\d{1,3})\s+(?:MA|SMA|EMA|moving[- ]average)\b",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_CAPITAL_RE = re.compile(
    r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:USDT|USD)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class BacktestIntent:
    symbol: str
    fast_window: int
    slow_window: int
    start_date: str
    end_date: str
    initial_capital: float
    strategy_type: str


def _has_backtest_word(prompt_lower: str) -> bool:
    return any(w in prompt_lower for w in _BACKTEST_WORDS)


def _has_ma_crossover(prompt_lower: str) -> bool:
    return any(w in prompt_lower for w in _MA_WORDS) and any(
        w in prompt_lower for w in _CROSSOVER_WORDS
    )


def _matches_blacklist(prompt_lower: str) -> bool:
    return any(tok in prompt_lower for tok in _BLACKLIST)


def _extract_windows(prompt: str) -> tuple:
    named = sorted({int(m.group(1)) for m in _WINDOW_NAMED_RE.finditer(prompt)})
    if len(named) >= 2:
        return named[0], named[-1]
    slash_m = _WINDOW_SLASH_RE.search(prompt)
    if slash_m:
        a, b = int(slash_m.group(1)), int(slash_m.group(2))
        return (min(a, b), max(a, b))
    return 20, 50


def _extract_dates(prompt: str) -> tuple:
    dates = _DATE_RE.findall(prompt)
    if len(dates) >= 2:
        return dates[0], dates[1]
    if len(dates) == 1:
        return dates[0], dates[0]
    return "", ""


def _extract_capital(prompt: str) -> float:
    m = _CAPITAL_RE.search(prompt)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return 10_000.0


def detect_backtest_intent(prompt: str) -> Optional[BacktestIntent]:
    if not prompt or not isinstance(prompt, str):
        return None
    prompt_lower = prompt.lower()
    if not _has_backtest_word(prompt_lower):
        return None
    if not _has_ma_crossover(prompt_lower):
        return None
    if _matches_blacklist(prompt_lower):
        return None
    raw_symbol = _extract_symbol(prompt)
    if raw_symbol is None:
        return None
    symbol = raw_symbol.replace("/", "-").upper()
    fast_window, slow_window = _extract_windows(prompt)
    start_date, end_date = _extract_dates(prompt)
    # Require explicit date range — without it the backtest has no period.
    if not start_date or not end_date:
        return None
    initial_capital = _extract_capital(prompt)
    return BacktestIntent(
        symbol=symbol,
        fast_window=fast_window,
        slow_window=slow_window,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        strategy_type="moving_average_crossover",
    )
