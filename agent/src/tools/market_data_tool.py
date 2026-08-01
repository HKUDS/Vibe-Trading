"""Local market data tool backed by the shared loader layer."""

from __future__ import annotations

from typing import Any

from src.agent.tools import BaseTool
from src.market_data import DEFAULT_MAX_ROWS, fetch_market_data_json


class MarketDataTool(BaseTool):
    """Fetch normalized OHLCV data through repository loaders."""

    name = "get_market_data"
    description = (
        "Fetch normalized OHLCV market data through the repository loader layer. "
        "Use this for stock, ETF, index, or crypto price bars before writing raw "
        "yfinance/OKX/Tushare scripts."
    )
    parameters = {
        "type": "object",
        "properties": {
            "codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'Symbols such as ["AAPL.US"], ["700.HK"], ["BTC-USDT"].',
            },
            "start_date": {
                "type": "string",
                "description": "Start date in YYYY-MM-DD format.",
            },
            "end_date": {
                "type": "string",
                "description": "End date in YYYY-MM-DD format.",
            },
            "source": {
                "type": "string",
                "enum": [
                    "auto",
                    "longbridge",
                    "yfinance",
                    "yahoo",
                    "okx",
                    "ccxt",
                    "tushare",
                    "baostock",
                    "tencent",
                    "akshare",
                    "mootdx",
                    "eastmoney",
                    "sina",
                    "stooq",
                    "finnhub",
                    "alphavantage",
                    "tiingo",
                    "fmp",
                    "mt5",
                    "pykrx",
                ],
                "description": (
                    "Data source. 'auto' detects from symbol format with fallback. "
                    "Use 'longbridge' explicitly for US/HK OHLCV through the "
                    "Longbridge OpenAPI (requires Longbridge credentials). "
                    "Free, no key: yfinance/yahoo (US/HK equities), okx/ccxt "
                    "(crypto), baostock/tencent/eastmoney/sina/akshare/mootdx "
                    "(China A-shares), stooq (global EOD), pykrx (Korea KRX daily "
                    "bars for <CODE>.KS / <CODE>.KQ; needs the optional pykrx "
                    "package, else Korea falls back to yahoo/yfinance). Key-gated "
                    "REST: tushare (China A-shares), finnhub/alphavantage/tiingo/fmp "
                    "(US/global). mt5: forex/metals from a local MetaTrader 5 "
                    "terminal (Windows; e.g. EUR/USD, XAUUSD.FX)."
                ),
                "default": "auto",
            },
            "interval": {
                "type": "string",
                "description": "Bar size, e.g. 1D, 1H, 4H, 30m.",
                "default": "1D",
            },
            "max_rows": {
                "type": "integer",
                "description": "Per-symbol row cap. Use 0 only when the full series is required.",
                "default": DEFAULT_MAX_ROWS,
            },
        },
        "required": ["codes", "start_date", "end_date"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        return fetch_market_data_json(
            codes=kwargs["codes"],
            start_date=kwargs["start_date"],
            end_date=kwargs["end_date"],
            source=kwargs.get("source", "auto"),
            interval=kwargs.get("interval", "1D"),
            max_rows=kwargs.get("max_rows", DEFAULT_MAX_ROWS),
            include_provenance=True,
        )
