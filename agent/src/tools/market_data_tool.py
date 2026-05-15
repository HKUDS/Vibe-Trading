"""First-class market-data tool: deterministic dispatch for price/OHLCV.

Replaces the prior path (load_skill + write_file + bash) for simple market-data
requests. Empirical bug fix: small LLMs (qwen2.5:7b) hallucinated skill names
("crypto-price") and looped on load_skill failures. This tool gives them one
deterministic entry point.

Fail-closed:
- Invalid symbol -> sanitized error, never raises.
- Provider failure -> sanitized error (no raw exception, URL, payload).
- NEVER falls back to web_search/read_url; that is a hard architectural rule.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)

_CRYPTO_QUOTES = ("USDT", "USD", "BTC", "ETH", "BUSD", "USDC")
_HK_SUFFIXES = (".HK",)
_A_SHARE_SUFFIXES = (".SH", ".SS", ".SZ")


def _normalize_symbol(symbol: str) -> tuple[str | None, str | None]:
    """Normalize a raw user symbol into (canonical, provider) or (None, None).

    Returns:
        Tuple of canonical symbol and auto-routed provider, or (None, None) if
        the input is not a recognised market-data symbol.
    """
    if not symbol or not isinstance(symbol, str):
        return None, None

    raw = symbol.strip().upper()
    if not raw or not re.match(r"^[A-Z0-9./\-]+$", raw):
        return None, None

    if any(raw.endswith(sfx) for sfx in _A_SHARE_SUFFIXES):
        return raw, "akshare"
    if any(raw.endswith(sfx) for sfx in _HK_SUFFIXES):
        return raw, "akshare"

    for quote in _CRYPTO_QUOTES:
        for sep in ("-", "/"):
            token = f"{sep}{quote}"
            if raw.endswith(token):
                base = raw[: -len(token)]
                if base and base.isalnum():
                    return f"{base}/{quote}", "ccxt"
        if raw.endswith(quote) and len(raw) > len(quote):
            base = raw[: -len(quote)]
            if base.isalpha():
                return f"{base}/{quote}", "ccxt"

    if raw.isalpha() and 1 <= len(raw) <= 5:
        return raw, "yfinance"

    return None, None


class MarketDataTool(BaseTool):
    """Fetch market price + OHLCV via ccxt / yfinance / akshare."""

    name = "get_market_data"
    description = (
        "Fetch current price + OHLCV for crypto pairs (BTC-USDT), US/HK stocks "
        "(AAPL, 0700.HK), or A-shares (600519.SH). ALWAYS use this for any "
        "price/ticker/OHLCV/candle/volume request — never web_search or "
        "read_url, never load_skill with an invented name. Output is JSON; "
        "format it as a markdown table for the user."
    )
    is_readonly = True
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Ticker: BTC-USDT / BTC/USDT / BTCUSDT, AAPL, 0700.HK, 600519.SH.",
            },
            "timeframe": {
                "type": "string",
                "description": "Candle granularity: 1d (default), 1h, 15m.",
                "default": "1d",
            },
            "limit": {
                "type": "integer",
                "description": "Number of recent candles to return (default 7).",
                "default": 7,
            },
            "provider": {
                "type": "string",
                "description": "Override auto-routing: ccxt | yfinance | akshare | auto (default).",
                "default": "auto",
            },
        },
        "required": ["symbol"],
    }

    def execute(self, **kwargs: Any) -> str:
        symbol = kwargs.get("symbol", "")
        timeframe = kwargs.get("timeframe", "1d")
        limit = int(kwargs.get("limit", 7))
        provider_arg = kwargs.get("provider", "auto")

        canonical, auto_provider = _normalize_symbol(symbol)
        if canonical is None:
            return json.dumps({
                "status": "error",
                "error": f"unrecognized symbol: {symbol!r}. Accepted: crypto pair (BTC-USDT), US ticker (AAPL), HK (0700.HK), A-share (600519.SH).",
            }, ensure_ascii=False)

        provider = provider_arg if provider_arg and provider_arg != "auto" else auto_provider
        if provider not in {"ccxt", "yfinance", "akshare"}:
            return json.dumps({
                "status": "error",
                "error": f"unsupported provider: {provider_arg!r}. Use ccxt | yfinance | akshare | auto.",
            }, ensure_ascii=False)

        try:
            if provider == "ccxt":
                data = self._fetch_ccxt(canonical, timeframe, limit)
            elif provider == "yfinance":
                data = self._fetch_yfinance(canonical, timeframe, limit)
            else:
                data = self._fetch_akshare(canonical, timeframe, limit)
        except Exception:
            logger.warning("market_data fail provider=%s symbol=%s reason=fetch_failed", provider, canonical)
            return json.dumps({
                "status": "error",
                "error": f"market data fetch failed (provider={provider}, symbol={canonical}).",
            }, ensure_ascii=False)

        logger.info("market_data ok provider=%s symbol=%s n=%d", provider, canonical, len(data.get("candles", [])))
        return json.dumps({
            "status": "ok",
            "symbol": canonical,
            "provider": provider,
            "timeframe": timeframe,
            "current_price": data.get("current_price"),
            "candles": data.get("candles", []),
        }, ensure_ascii=False)

    def _fetch_ccxt(self, symbol: str, timeframe: str, limit: int) -> dict[str, Any]:
        import ccxt
        from datetime import datetime, timezone

        exchange = ccxt.binance({"enableRateLimit": True})
        ticker = exchange.fetch_ticker(symbol)
        raw = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        candles = [
            {
                "date": datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
            }
            for row in raw
        ]
        return {"current_price": ticker.get("last"), "candles": candles}

    def _fetch_yfinance(self, symbol: str, timeframe: str, limit: int) -> dict[str, Any]:
        import yfinance as yf

        interval_map = {"1d": "1d", "1h": "1h", "15m": "15m"}
        interval = interval_map.get(timeframe, "1d")
        period_days = max(limit * 2, 14)
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=f"{period_days}d", interval=interval).tail(limit)
        candles = [
            {
                "date": idx.strftime("%Y-%m-%d"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            }
            for idx, row in hist.iterrows()
        ]
        current = candles[-1]["close"] if candles else None
        return {"current_price": current, "candles": candles}

    def _fetch_akshare(self, symbol: str, timeframe: str, limit: int) -> dict[str, Any]:
        import akshare as ak

        if symbol.endswith(".HK"):
            code = symbol.replace(".HK", "").zfill(5)
            df = ak.stock_hk_hist(symbol=code, period="daily").tail(limit)
        else:
            code = symbol.split(".")[0]
            df = ak.stock_zh_a_hist(symbol=code, period="daily").tail(limit)
        candles = [
            {
                "date": str(row[df.columns[0]]),
                "open": float(row["开盘"] if "开盘" in df.columns else row.iloc[1]),
                "high": float(row["最高"] if "最高" in df.columns else row.iloc[3]),
                "low": float(row["最低"] if "最低" in df.columns else row.iloc[4]),
                "close": float(row["收盘"] if "收盘" in df.columns else row.iloc[2]),
                "volume": float(row["成交量"] if "成交量" in df.columns else row.iloc[5]),
            }
            for _, row in df.iterrows()
        ]
        current = candles[-1]["close"] if candles else None
        return {"current_price": current, "candles": candles}
