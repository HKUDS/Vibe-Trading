"""Local market data tool backed by the shared loader layer."""

from __future__ import annotations

import json
import re
from datetime import date

from typing import Any

from src.agent.tools import BaseTool
from src.market_data import DEFAULT_MAX_ROWS, fetch_market_data_json
from backtest.loaders.registry import VALID_SOURCES
from backtest.runner import _VALID_INTERVALS

# Canonical-case lookup: `_VALID_INTERVALS` mixes cases ("1m" minutes vs "1H"
# hours), so a plain `.upper()` would turn valid "1m"/"5m"/"15m"/"30m" into
# "1M"/"5M"/… which loaders reject. Map any case spelling to the canonical
# form the loaders expect ("1d" -> "1D", "30M" -> "30m").
_INTERVAL_CANON = {v.upper(): v for v in _VALID_INTERVALS}

# Source allow-list derived from the shared loader registry (the same set the
# backtest tool validates against), so the MCP/agent-facing surface can never
# silently drop a loader the registry serves. Sorted for a stable schema.
_SOURCE_ENUM = sorted(VALID_SOURCES)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _error(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _valid_iso_date(value: str) -> bool:
    """True only for strict ``YYYY-MM-DD`` calendar dates.

    ``date.fromisoformat`` alone is not enough: on Python 3.11+ it also
    accepts the compact ``YYYYMMDD`` form, which loaders downstream reject
    or mis-parse. Enforce the exact shape first, then the calendar.
    """
    if not _ISO_DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


class MarketDataTool(BaseTool):
    """Fetch normalized OHLCV data through repository loaders."""

    name = "get_market_data"
    description = (
        "Fetch normalized OHLCV market data through the repository loader layer. "
        "Use this for stock, ETF, index, or crypto price bars before writing raw "
        "yfinance/OKX/Tushare scripts. Volume units are source- and market-dependent "
        "(A-share sources report board lots of 100 shares, HK/US sources report single "
        "shares); read the per-symbol _provenance.volume_unit field ('lots' / 'shares' / "
        "null=undeclared) before interpreting or comparing volume values. Price caliber "
        "is source-dependent too (some sources adjust for splits/dividends, others serve "
        "raw quotes); read _provenance.adjustment ('raw' / 'split' / 'split_dividend' / "
        "'na' / 'unknown') before comparing price levels across symbols."
    )
    parameters = {
        "type": "object",
        "properties": {
            "codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    'Symbols such as ["AAPL.US"], ["700.HK"], ["TD.TO"], '
                    '["PNG.V"], or ["BTC-USDT"].'
                ),
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
                "enum": _SOURCE_ENUM,
                "description": (
                    "Data source. 'auto' detects from symbol format with fallback. "
                    "Use 'longbridge' explicitly for US/HK OHLCV through the "
                    "Longbridge OpenAPI (requires Longbridge credentials). "
                    "Free, no key: yfinance/yahoo (US/HK/Canada equities; "
                    "Canada uses .TO/.V), okx/ccxt/binance "
                    "(crypto), baostock/tencent/eastmoney/sina/akshare/mootdx "
                    "(China A-shares), futu (HK/A via local FutuOpenD), stooq "
                    "(global EOD), pykrx (Korea KRX daily "
                    "bars for <CODE>.KS / <CODE>.KQ; needs the optional pykrx "
                    "package, else Korea falls back to yahoo/yfinance). Key-gated "
                    "REST: tushare (China A-shares), finnhub/alphavantage/tiingo/fmp "
                    "(US/global), qveris (premium marketplace). india_broker: "
                    "read-only Shoonya/Dhan bars for .NS/.BO. mt5: forex/metals "
                    "from a local MetaTrader 5 terminal (Windows; e.g. EUR/USD, "
                    "XAUUSD.FX); tickerall: the same feed hosted, no terminal, "
                    "any OS. local: your own CSV/Parquet/DuckDB files."
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
        """Validate inputs, then fetch and return strict JSON.

        Args:
            **kwargs: ``codes``, ``start_date``, ``end_date``, optional
                ``source``, ``interval``, ``max_rows``, and (internal,
                MCP-only) ``loader_resolver`` — the resolver the MCP server
                injects so its own loader-hook contract is preserved.

        Returns:
            Strict JSON envelope with per-symbol OHLCV panels plus
            ``_provenance``, or an error envelope on invalid inputs.
        """
        codes = kwargs.get("codes")
        if not isinstance(codes, list) or not codes:
            return _error("codes must be a non-empty list of strings")
        if any(not isinstance(code, str) or not code.strip() for code in codes):
            return _error("every code must be a non-empty string")
        codes = [code.strip() for code in codes]

        start_date = kwargs.get("start_date")
        end_date = kwargs.get("end_date")
        if not isinstance(start_date, str) or not start_date.strip():
            return _error("start_date must be a non-empty YYYY-MM-DD string")
        if not isinstance(end_date, str) or not end_date.strip():
            return _error("end_date must be a non-empty YYYY-MM-DD string")
        start_date = start_date.strip()
        end_date = end_date.strip()
        if not _valid_iso_date(start_date) or not _valid_iso_date(end_date):
            return _error("start_date and end_date must be valid YYYY-MM-DD dates")
        if start_date > end_date:
            return _error(
                f"start_date ({start_date}) must not be after end_date ({end_date})"
            )

        source = kwargs.get("source", "auto")
        if source not in _SOURCE_ENUM:
            return _error(f"source must be one of {_SOURCE_ENUM}")

        interval = kwargs.get("interval", "1D")
        if not isinstance(interval, str):
            return _error("interval must be a string like '1D', '1H', '4H', '30m'")
        normalized_interval = _INTERVAL_CANON.get(interval.strip().upper())
        if normalized_interval is None:
            return _error(
                f"interval must be one of {sorted(_VALID_INTERVALS)} "
                f"(case-insensitive); got {interval!r}"
            )

        max_rows = kwargs.get("max_rows", DEFAULT_MAX_ROWS)
        if not isinstance(max_rows, int) or isinstance(max_rows, bool):
            return _error("max_rows must be a non-negative integer (0 = all rows)")
        if max_rows < 0:
            # P07 contract (test_get_market_data_size.py::G3ii): a negative
            # cap is invalid but must never become unbounded — the loader
            # layer clamps it to the default cap. Keep that observable
            # behavior here so both surfaces agree.
            max_rows = DEFAULT_MAX_ROWS

        fetch_kwargs: dict[str, Any] = {
            "codes": codes,
            "start_date": start_date,
            "end_date": end_date,
            "source": source,
            "interval": normalized_interval,
            "max_rows": max_rows,
            "include_provenance": True,
        }
        loader_resolver = kwargs.get("loader_resolver")
        if loader_resolver is not None:
            fetch_kwargs["loader_resolver"] = loader_resolver
        return fetch_market_data_json(**fetch_kwargs)
