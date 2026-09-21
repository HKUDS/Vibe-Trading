"""Gildata (恒生聚源) loader: token-gated A-share OHLCV via the raw-api MCP endpoint.

Gildata serves its market data over MCP streamable-HTTP: every tool call is one
JSON-RPC POST to a single endpoint, with the token in the Authorization header::

    POST https://api.gildata.com/mcp-servers/aidata-assistant-srv-rawapi?format=json
         Authorization: Bearer <GILDATA_TOKEN>
    {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
     "params": {"name": "StockDailyQuote", "arguments": {...}}}

The ``format=json`` parameter makes the tool answer with structured JSON
instead of markdown. The JSON-RPC ``result.content[0].text`` field carries an
inner envelope ``{"code": 0, "results": [{"api_name", "columns", "rows"}]}``;
a non-zero inner ``code`` (e.g. 1001 on a bad token) is an error, while an
*unresolvable symbol silently yields ``rows: []``* — the loader must treat
that as "no data" so the fallback chain keeps walking, not as a hard failure.

This loader uses the ``StockDailyQuote`` tool (A-share daily bars):

* ``stockObject`` accepts project-style ``600519.SH`` codes directly (no
  internal-code recall needed for A-shares, unlike the HK/US/index tools);
* ``restorationStatus=1`` selects 前复权 (forward, split-AND-dividend
  adjusted) — the same caliber tushare serves via ``adj_factor``;
* one call covers the full requested window (verified against a 6.7-year
  range) and up to 50 symbols; this loader still fetches per symbol so each
  frame flows through the per-symbol loader cache;
* ``turnovervolume`` is reported in 万股 (10k shares) and is converted to
  plain shares here — ``volume_units`` therefore declares ``"shares"``.

Auth: set ``GILDATA_TOKEN`` in the environment (apply via the vendor's sales
channel, datamap@gildata.com). ``GILDATA_BASE_URL`` can override the endpoint.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.loaders._http import resolve_min_interval, throttled_post_json
from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_TOKEN_ENV = "GILDATA_TOKEN"
_BASE_URL_ENV = "GILDATA_BASE_URL"
_DEFAULT_BASE_URL = "https://api.gildata.com/mcp-servers/aidata-assistant-srv-rawapi"

# Tokens that must not count as "configured" (mirrors tushare's placeholder set).
GILDATA_TOKEN_PLACEHOLDERS = {"", "your-gildata-token"}

# Shared throttle/session bucket for every Gildata request in this process.
_HOST_KEY = "gildata"
_MIN_INTERVAL_ENV = "VIBE_TRADING_GILDATA_MIN_INTERVAL"
_DEFAULT_MIN_INTERVAL_S = 0.3
_TIMEOUT_S = 30.0

# The MCP tool this loader routes to (A-share daily bars, 前复权).
_DAILY_QUOTE_TOOL = "StockDailyQuote"
_RESTORATION_QFQ = "1"  # 1-前复权 / 2-后复权 / 3-不复权

# Emitted columns, in this order, all float.
_OHLCV_FIELDS = ("open", "high", "low", "close", "volume")

# 万股 (10k shares) -> shares.
_VOLUME_UNIT_MULTIPLIER = 10_000.0


def _token() -> str:
    """Return the configured Gildata token, stripped (``""`` if unset)."""
    from src.config.accessor import get_env_config

    return get_env_config().data.gildata_token.strip()


def _base_url() -> str:
    """Return the raw-api endpoint URL (env-overridable)."""
    from src.config.accessor import get_env_config

    return get_env_config().data.gildata_base_url.strip() or _DEFAULT_BASE_URL


def _min_interval() -> float:
    """Resolve the per-call minimum spacing, honoring the env override."""
    return resolve_min_interval(_MIN_INTERVAL_ENV, _DEFAULT_MIN_INTERVAL_S)


def _gildata_symbol(code: str) -> Optional[str]:
    """Translate a project symbol into Gildata's A-share convention.

    Gildata A-share tools accept ``代码.交易所后缀`` with the SH/SZ/BJ
    suffixes. The project already uses that shape, so suffixed codes pass
    through (with ``.SS`` normalized to ``.SH`` like everywhere else). A bare
    6-digit code gets its exchange inferred from the leading digit. Anything
    that is not recognizably an A-share symbol returns ``None`` so the caller
    can drop it and let the fallback chain serve it from another source.

    Args:
        code: Project symbol, e.g. ``600519.SH``, ``000001``, ``00700.HK``.

    Returns:
        The Gildata symbol, or ``None`` for non-A-share inputs.
    """
    upper = code.strip().upper()
    if not upper:
        return None
    if upper.endswith(".SS"):
        upper = upper[: -len(".SS")] + ".SH"
    if upper.endswith((".SH", ".SZ", ".BJ")):
        digits = upper.split(".")[0]
        return upper if len(digits) == 6 and digits.isdigit() else None
    if len(upper) == 6 and upper.isdigit():
        # Bare codes: 5/6/9 -> SH, 0/3 -> SZ, 4/8 -> BJ (BSE/NEEQ ranges).
        if upper[0] in "569":
            return upper + ".SH"
        if upper[0] in "03":
            return upper + ".SZ"
        if upper[0] in "48":
            return upper + ".BJ"
        return None
    return None


def _call_tool(tool: str, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Invoke one MCP tool and return its ``rows``.

    Args:
        tool: Tool name, e.g. ``"StockDailyQuote"``.
        arguments: Structured tool arguments.

    Returns:
        The ``rows`` list of the first result entry (empty when the vendor
        reports no data for the request).

    Raises:
        RuntimeError: If the token is missing, or the vendor answers with a
            non-zero business code (bad token, quota, bad request).
        requests.RequestException: Propagated from the HTTP layer.
        ValueError: If the response shape cannot be unwrapped.
    """
    token = _token()
    if not token:
        raise RuntimeError(f"{_TOKEN_ENV} is not set")

    base = _base_url()
    # The token rides the Authorization header, never the URL: request
    # exceptions (DNS failure, timeout) embed the full URL in their message,
    # and a query-string token would leak into those logs (review of #1474).
    url = f"{base}{'&' if '?' in base else '?'}format=json"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    outer = throttled_post_json(
        url,
        host_key=_HOST_KEY,
        min_interval=_min_interval(),
        json_body=payload,
        # MCP streamable-HTTP servers reject requests whose Accept header
        # does not name both content types (measured: 400 without it).
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        },
        timeout=_TIMEOUT_S,
    )

    # Without a valid token the endpoint answers HTTP 200 with a plain error
    # object (no JSON-RPC result envelope) — surface its message.
    result = outer.get("result") if isinstance(outer, dict) else None
    if result is None:
        message = outer.get("message") if isinstance(outer, dict) else None
        raise RuntimeError(f"gildata MCP call failed: {message or outer!r}")

    content = result.get("content") or []
    if not content or not isinstance(content[0], dict):
        raise ValueError(f"gildata MCP response has no content: {outer!r}")
    text = content[0].get("text")
    if not isinstance(text, str):
        raise ValueError(f"gildata MCP content is not text: {content[0]!r}")

    inner = json.loads(text)
    if not isinstance(inner, dict) or inner.get("code") not in (0, "0"):
        raise RuntimeError(
            f"gildata tool {tool} returned error: {str(inner)[:200]}"
        )
    results = inner.get("results") or []
    if not results:
        return []
    rows = results[0].get("rows")
    return rows if isinstance(rows, list) else []


def _parse_daily_rows(rows: List[Dict[str, Any]]) -> Optional[pd.DataFrame]:
    """Convert ``StockDailyQuote`` rows into an ascending OHLCV frame.

    Field names come from the tool's own ``columns`` map (``tradingday``,
    ``openprice``/``highprice``/``lowprice``/``closeprice``,
    ``turnovervolume`` in 万股). The ``avgprice``/``prevcloseprice`` fields
    are deliberately ignored: on adjusted series they stay on a different
    adjustment basis than OHLC (measured on 600519: qfq close 1491 vs
    avgprice 1666), so mixing them in would corrupt prices.

    Args:
        rows: Raw row dicts from :func:`_call_tool`.

    Returns:
        DataFrame indexed by ``trade_date`` with float ``open/high/low/close/
        volume`` columns (volume converted to shares), or ``None`` when no
        usable rows are present.
    """
    # Date key differs across the vendor's quote tools (tradingday/enddate);
    # accept both so a tool swap never silently empties the frame.
    def _date(row: Dict[str, Any]) -> Any:
        return row.get("tradingday") or row.get("enddate")

    records = [
        {
            "trade_date": _date(row),
            "open": row.get("openprice"),
            "high": row.get("highprice"),
            "low": row.get("lowprice"),
            "close": row.get("closeprice"),
            "volume": row.get("turnovervolume"),
        }
        for row in rows
        if isinstance(row, dict)
    ]
    records = [record for record in records if record["trade_date"]]
    if not records:
        return None

    df = pd.DataFrame(records)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    for field in _OHLCV_FIELDS:
        # Cast to float (not just to_numeric) so the float-OHLCV contract
        # holds even when the vendor sends integers or numeric strings.
        df[field] = pd.to_numeric(df[field], errors="coerce").astype(float)
    # 万股 -> shares; suspended days may arrive without a volume reading.
    df["volume"] = (df["volume"] * _VOLUME_UNIT_MULTIPLIER).fillna(0.0)

    df = df.set_index("trade_date").sort_index()
    df = df[list(_OHLCV_FIELDS)].dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        return None
    return df


@register
class DataLoader:
    """Gildata A-share OHLCV loader (token-gated, MCP-over-HTTP)."""

    name = "gildata"
    markets = {"a_share"}
    requires_auth = True
    # turnovervolume is converted from 万股 to shares before serving.
    volume_units = {"a_share": "shares"}

    def __init__(self) -> None:
        pass

    def is_available(self) -> bool:
        """Available when ``GILDATA_TOKEN`` is set to a non-placeholder value."""
        return _token() not in GILDATA_TOKEN_PLACEHOLDERS

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch daily OHLCV bars from Gildata, one symbol at a time.

        Non-A-share symbols are dropped (the fallback chain serves them from
        another source), and a single failing symbol is logged and skipped so
        it never aborts the rest of the batch.

        Args:
            codes: Project symbols (e.g. ``["600519.SH", "000001.SZ"]``).
            start_date: Inclusive start date, ``YYYY-MM-DD``.
            end_date: Inclusive end date, ``YYYY-MM-DD``.
            interval: Bar size; only ``"1D"`` is supported (others skipped).
            fields: Ignored — Gildata returns a fixed OHLCV schema.

        Returns:
            Mapping ``{symbol: DataFrame(trade_date, open, high, low, close,
            volume)}`` for every A-share symbol that returned non-empty data.

        Raises:
            ValueError: If ``start_date`` > ``end_date`` (via
                :func:`validate_date_range`).
        """
        validate_date_range(start_date, end_date)

        if str(interval).strip().lower() not in {"1d", "d", "day", "daily"}:
            logger.warning("gildata only supports 1D bars; got interval=%r", interval)
            return {}

        if not self.is_available():
            logger.warning("gildata fetch skipped: %s not set", _TOKEN_ENV)
            return {}

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            symbol = _gildata_symbol(code)
            if symbol is None:
                logger.debug("gildata skipping non-A-share symbol %r", code)
                continue
            try:
                df = cached_loader_fetch(
                    source=self.name,
                    symbol=code,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda symbol=symbol: self._fetch_one(
                        symbol, start_date, end_date
                    ),
                )
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:
                logger.warning("gildata failed for %s: %s", code, exc)
        return result

    def _fetch_one(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch and parse one symbol's daily bars; ``None`` on no data.

        Args:
            symbol: Normalized Gildata symbol (e.g. ``600519.SH``).
            start_date: Inclusive start date, ``YYYY-MM-DD``.
            end_date: Inclusive end date, ``YYYY-MM-DD``.

        Returns:
            An ascending OHLCV DataFrame indexed by ``trade_date``, or ``None``
            when Gildata reports no bars for the symbol/window.

        Raises:
            RuntimeError: If the token is missing or the vendor errors.
            requests.RequestException: Propagated from the HTTP layer.
        """
        rows = _call_tool(
            _DAILY_QUOTE_TOOL,
            {
                "stockObject": [symbol],
                "beginDate": start_date,
                "endDate": end_date,
                "restorationStatus": _RESTORATION_QFQ,
            },
        )
        return _parse_daily_rows(rows)
