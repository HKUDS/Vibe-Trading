"""Read-only technical indicator tool.

Computes RSI, MACD, Bollinger Bands, SMA, and EMA for a given symbol using the
existing market-data pipeline. All computation is pure Python (numpy/pandas);
no new dependencies.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from src.agent.tools import BaseTool
from src.market_data import fetch_market_data

logger = logging.getLogger(__name__)

# ── Indicator defaults ────────────────────────────────────────────────────────
_RSI_PERIOD = 14
_MACD_FAST = 12
_MACD_SLOW = 26
_MACD_SIGNAL = 9
_BB_PERIOD = 20
_BB_STD = 2.0
_SMA_PERIODS = (20, 50, 200)
_EMA_PERIOD = 20
_DEFAULT_LOOKBACK = 200
_MAX_LOOKBACK = 500


_CLOSE_KEYS = ("close", "Close", "CLOSE", "adj_close")
_DATE_KEYS = ("trade_date", "date", "datetime", "timestamp", "time")


def _extract_close_series(payload: Any) -> pd.Series | None:
    """Extract the close-price series from a loader payload.

    Loader results can be a ``DataFrame``, a plain column mapping, or the
    ``list[dict]`` shape returned by :func:`fetch_market_data`. Preserve a real
    date index when one is available; a payload without dates intentionally
    keeps a ``RangeIndex`` so callers do not report a row number as a date.
    """
    if isinstance(payload, list):
        if not payload or not isinstance(payload[0], dict):
            return None
        frame = pd.DataFrame(payload)
    elif isinstance(payload, dict):
        inner = payload.get("data")
        if isinstance(inner, list):
            return _extract_close_series(inner)
        try:
            frame = pd.DataFrame(payload)
        except ValueError:
            return None
    elif isinstance(payload, pd.DataFrame):
        frame = payload.copy()
    else:
        return None

    close_key = next((key for key in _CLOSE_KEYS if key in frame.columns), None)
    if close_key is None:
        return None

    close = pd.to_numeric(frame[close_key], errors="coerce")
    date_key = next((key for key in _DATE_KEYS if key in frame.columns), None)
    if date_key is not None:
        dates = pd.to_datetime(frame[date_key], errors="coerce")
    elif isinstance(frame.index, pd.DatetimeIndex):
        dates = pd.Series(frame.index, index=frame.index)
    elif not isinstance(frame.index, pd.RangeIndex) and not pd.api.types.is_integer_dtype(
        frame.index.dtype
    ):
        dates = pd.Series(pd.to_datetime(frame.index, errors="coerce"), index=frame.index)
    else:
        return close.dropna().reset_index(drop=True).astype(float)

    valid = close.notna() & dates.notna()
    normalized = pd.Series(
        close.loc[valid].to_numpy(dtype=float),
        index=pd.DatetimeIndex(dates.loc[valid]),
        dtype=float,
    )
    return normalized.sort_index(kind="stable")


def _compute_sma(close: pd.Series, period: int) -> float | None:
    """Simple moving average over the last *period* bars."""
    if len(close) < period:
        return None
    return float(close.iloc[-period:].mean())


def _compute_ema(close: pd.Series, period: int) -> float | None:
    """Exponential moving average over the full series."""
    if len(close) < period:
        return None
    return float(close.ewm(span=period, adjust=False).mean().iloc[-1])


def _compute_rsi(close: pd.Series, period: int = _RSI_PERIOD) -> float | None:
    """Relative Strength Index (Wilder smoothing) over *period* bars."""
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(window=period).mean().iloc[-1]
    avg_loss = loss.rolling(window=period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _compute_macd(
    close: pd.Series,
    fast: int = _MACD_FAST,
    slow: int = _MACD_SLOW,
    signal: int = _MACD_SIGNAL,
) -> dict[str, float | None] | None:
    """MACD line, signal line, and histogram."""
    if len(close) < slow + signal:
        return None
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {
        "macd_line": round(float(macd_line.iloc[-1]), 4),
        "signal_line": round(float(signal_line.iloc[-1]), 4),
        "histogram": round(float(histogram.iloc[-1]), 4),
    }


def _compute_bollinger(
    close: pd.Series,
    period: int = _BB_PERIOD,
    num_std: float = _BB_STD,
) -> dict[str, float | None] | None:
    """Bollinger Bands: upper, middle (SMA), lower."""
    if len(close) < period:
        return None
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    return {
        "upper": round(float(sma.iloc[-1] + num_std * std.iloc[-1]), 2),
        "middle": round(float(sma.iloc[-1]), 2),
        "lower": round(float(sma.iloc[-1] - num_std * std.iloc[-1]), 2),
    }


class TechnicalIndicatorTool(BaseTool):
    """Compute common technical indicators for a symbol.

    Fetches OHLCV data through the existing loader pipeline, then computes
    RSI, MACD, Bollinger Bands, SMA, and EMA. All math is pure Python; no
    new dependencies, no network calls beyond what the loaders already do.
    """

    name = "technical_indicators"
    description = (
        "Compute common technical indicators (RSI, MACD, Bollinger Bands, "
        "SMA, EMA) for a trading symbol. Uses the project's data loaders "
        "to fetch price history, then computes indicators locally."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": (
                    "Trading symbol, e.g. AAPL for US stocks, "
                    "600519.SH for A-shares, BTC-USDT for crypto."
                ),
            },
            "interval": {
                "type": "string",
                "description": "Bar interval: 1d (default), 1wk, or 1mo.",
                "default": "1d",
            },
            "lookback": {
                "type": "integer",
                "description": (
                    "Number of bars to fetch. Default 200, max 500. "
                    "More bars = more accurate long-term indicators (SMA 200)."
                ),
                "default": _DEFAULT_LOOKBACK,
            },
        },
        "required": ["symbol"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        symbol = str(kwargs.get("symbol", "")).strip()
        interval = str(kwargs.get("interval", "1d")).strip()
        lookback_raw = kwargs.get("lookback", _DEFAULT_LOOKBACK)

        if not symbol:
            return json.dumps({"ok": False, "error": "symbol is required"})

        try:
            lookback = int(lookback_raw)
        except (TypeError, ValueError):
            lookback = _DEFAULT_LOOKBACK
        lookback = max(10, min(lookback, _MAX_LOOKBACK))

        # Fetch enough bars to cover the longest indicator window + buffer.
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=lookback * 2)).strftime("%Y-%m-%d")

        try:
            data = fetch_market_data(
                codes=[symbol],
                start_date=start_date,
                end_date=end_date,
                interval=interval,
                # Indicators require consecutive bars. ``max_rows=lookback``
                # would make the shared helper even-stride sample long windows.
                max_rows=0,
            )
        except Exception as exc:
            logger.debug("fetch_market_data failed for %s: %s", symbol, exc)
            return json.dumps({"ok": False, "error": f"Failed to fetch data: {exc}"})

        df = data.get(symbol)
        if df is None:
            return json.dumps({"ok": False, "error": f"No data returned for {symbol}"})
        if isinstance(df, pd.DataFrame) and df.empty:
            return json.dumps({"ok": False, "error": f"No data returned for {symbol}"})
        if isinstance(df, list) and not df:
            return json.dumps({"ok": False, "error": f"No data returned for {symbol}"})
        if isinstance(df, dict) and not df:
            return json.dumps({"ok": False, "error": f"No data returned for {symbol}"})
        if isinstance(df, dict) and df.get("truncated") is True:
            return json.dumps(
                {
                    "ok": False,
                    "error": "Indicator calculation requires consecutive, untruncated bars",
                }
            )

        close = _extract_close_series(df)
        if close is None or close.empty:
            return json.dumps({"ok": False, "error": "No close price column in data"})
        close = close.sort_index(kind="stable").tail(lookback)

        # ── Compute indicators ────────────────────────────────────────────
        indicators: dict[str, Any] = {
            "rsi_14": _compute_rsi(close),
            "macd": _compute_macd(close),
            "bollinger": _compute_bollinger(close),
        }
        for period in _SMA_PERIODS:
            indicators[f"sma_{period}"] = _compute_sma(close, period)
        indicators[f"ema_{_EMA_PERIOD}"] = _compute_ema(close, _EMA_PERIOD)

        latest_close = float(close.iloc[-1]) if len(close) > 0 else None
        latest_date = (
            str(close.index[-1])[:10]
            if isinstance(close.index, pd.DatetimeIndex) and len(close) > 0
            else None
        )

        return json.dumps(
            {
                "ok": True,
                "symbol": symbol,
                "interval": interval,
                "latest_close": latest_close,
                "latest_date": latest_date,
                "indicators": indicators,
            },
            ensure_ascii=False,
            default=str,
        )
