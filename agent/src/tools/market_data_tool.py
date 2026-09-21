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

# Canonical-case lookup. ``_VALID_INTERVALS`` mixes cases ("1m" minutes vs
# "1H" hours), so a plain ``.upper()`` fold is unsafe: it maps the universal
# monthly spelling "1M" onto "1m" (one minute), silently answering a monthly
# question with minute bars (#1480). ``_canonicalize_interval`` resolves a
# case-exact match first and only then falls back to this fold for the
# unambiguous case variants ("1d" -> "1D", "30M" -> "30m").
_INTERVAL_CANON = {v.upper(): v for v in _VALID_INTERVALS}

# Spellings that read as a request for a bar size this tool does not serve and
# must never be case-folded onto a minute interval. "1M" is the near-universal
# monthly convention (pandas ``resample('1M')``, ccxt / TradingView "1M"); "1W"
# is weekly. Folding "1M" -> "1m" (one minute) is the #1480 footgun: the caller
# receives minute bars labelled as the answer to a monthly question. These are
# rejected with a pointed message instead of being silently mis-served. The
# minute spellings "5M" / "15M" / "30M" deliberately keep folding to "5m" /
# "15m" / "30m" — multi-month bars are not a convention anyone requests, and
# that fold is the documented behaviour pinned by the regression tests.
_UNSUPPORTED_PERIOD_SPELLINGS = {"1M": "one month", "1W": "one week"}


def _canonicalize_interval(raw: str) -> str | None:
    """Resolve a user interval spelling to the canonical loader form.

    A case-exact match against ``_VALID_INTERVALS`` wins first, so the minute
    interval ``"1m"`` and the monthly spelling ``"1M"`` are never conflated by
    the case fold (#1480). Falls back to ``_INTERVAL_CANON`` for unambiguous
    case variants (``"1d"`` -> ``"1D"``, ``"30M"`` -> ``"30m"``). Month/week
    spellings that are not served resolve to ``None`` rather than folding onto
    a minute interval.

    Args:
        raw: Interval string as supplied by the caller.

    Returns:
        The canonical interval token, or ``None`` when not served.
    """
    token = raw.strip()
    if token in _VALID_INTERVALS:
        return token
    folded = token.upper()
    if folded in _UNSUPPORTED_PERIOD_SPELLINGS:
        return None
    return _INTERVAL_CANON.get(folded)


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
        interval_token = interval.strip()
        # Reject the month/week spellings the case fold would otherwise map onto
        # a minute interval: "1M" (one month) must never silently become "1m"
        # (one minute) (#1480). A case-exact served spelling is allowed through
        # first, so this stays correct if monthly/weekly bars are ever added to
        # ``_VALID_INTERVALS`` (#1479).
        folded = interval_token.upper()
        if (
            interval_token not in _VALID_INTERVALS
            and folded in _UNSUPPORTED_PERIOD_SPELLINGS
        ):
            return _error(
                f"interval {interval_token!r} ({_UNSUPPORTED_PERIOD_SPELLINGS[folded]}) "
                f"is not supported; supported: {sorted(_VALID_INTERVALS)}. "
                f"Note '1m' (lowercase) is one minute."
            )
        normalized_interval = _canonicalize_interval(interval_token)
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
