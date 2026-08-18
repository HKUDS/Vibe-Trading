"""Read-only fund-flow (capital-flow) tool backed by the Eastmoney client.

Eastmoney publishes a free, no-auth capital-flow series that splits each bar's
net inflow into main / large / medium / small-order buckets (the
"主力/超大单/大单/中单/小单" decomposition). Two ``fflow`` endpoints serve it:
a daily history line and an intraday (minute) line. Both are addressed by the
same ``secid`` scheme used for klines, so symbol resolution and HTTP throttling
are delegated to :mod:`backtest.loaders.eastmoney_client` (every request routes
through the shared per-host throttle — Eastmoney rate-limits by IP and bans
bursting clients).

Markets: A-share (``.SH`` / ``.SZ`` / ``.BJ``), Hong Kong (``.HK``) and US
(``.US``). One unresolvable or failing symbol never aborts the batch.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from backtest.loaders.eastmoney_client import get_json, resolve_secid
from src.agent.tools import BaseTool
from src.tools import tushare_fallbacks

logger = logging.getLogger(__name__)

# Eastmoney capital-flow endpoints. ``daykline`` is the daily history line;
# ``kline`` is the intraday (per-minute) line for the current session.
_DAILY_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
_MINUTE_URL = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"

# Per-bar field selectors. The daily line carries date + the five net-inflow
# buckets; the minute line carries time + the same five buckets (no leading
# date, since all bars share the current trading day).
_DAILY_FIELDS = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
_MINUTE_FIELDS = "f51,f52,f53,f54,f55,f56"

# Bucket labels in the order Eastmoney emits them after the leading timestamp:
# main (主力净额), small, medium, large, super-large net inflow in CNY.
_BUCKETS = ("main", "small", "medium", "large", "super_large")

# Defensive caps so a payload can never blow up the LLM context.
_MAX_DAYS = 250
_MAX_ROWS_PER_SYMBOL = 250
_VALID_PERIODS = ("min", "daily")
_SINA_FLOW_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_qsfx_zjlrqs"


def _error(message: str) -> str:
    """Build the failure envelope as a JSON string.

    Args:
        message: Human-readable error description.

    Returns:
        A ``{"ok": false, "error": ...}`` JSON string.
    """
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _parse_flow_row(raw: str) -> dict[str, Any] | None:
    """Parse one comma-joined fflow row into a labelled net-inflow dict.

    Daily rows lead with a ``YYYY-MM-DD`` date; minute rows lead with a
    ``YYYY-MM-DD HH:MM`` timestamp. Either way the next five columns are the
    main / small / medium / large / super-large net inflow values in CNY.

    Args:
        raw: One row string from ``data.klines``.

    Returns:
        A dict ``{timestamp, main, small, medium, large, super_large}``, or
        ``None`` when the row is too short or carries non-numeric buckets.
    """
    parts = raw.split(",")
    if len(parts) < 1 + len(_BUCKETS):
        return None
    timestamp = parts[0]
    try:
        values = [float(parts[i + 1]) for i in range(len(_BUCKETS))]
    except (ValueError, TypeError):
        return None
    row: dict[str, Any] = {"timestamp": timestamp}
    row.update(dict(zip(_BUCKETS, values)))
    return row


def _sina_market_code(symbol: str) -> str:
    """Convert a Vibe-Trading symbol to Sina's lowercase market prefix form."""
    token = symbol.strip().upper()
    bare, _, suffix = token.partition(".")
    if suffix in {"SH", "SZ", "BJ"}:
        market = suffix.lower()
    else:
        bare = token.removeprefix("SH").removeprefix("SZ").removeprefix("BJ")
        if bare.startswith(("5", "6", "9")):
            market = "sh"
        elif bare.startswith(("0", "2", "3")):
            market = "sz"
        elif bare.startswith(("4", "8")):
            market = "bj"
        else:
            raise ValueError(f"unsupported Sina symbol: {symbol}")
    if len(bare) != 6 or not bare.isdigit():
        raise ValueError(f"unsupported Sina symbol: {symbol}")
    return f"{market}{bare}"


def _sina_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_sina_daily_flow(symbol: str, *, days: int) -> dict[str, Any]:
    """Fetch Sina's daily flow and normalize amounts to CNY.

    This Sina endpoint is not equivalent to Eastmoney's five-bucket feed. In
    live responses it normally exposes ``r0_net`` (main-force net inflow) and
    ``netamount`` (overall net inflow), while the order-size fields may be
    absent. Values are returned by the endpoint in CNY despite some older
    descriptions calling them "ten-thousand CNY". Missing buckets therefore
    stay ``None`` instead of being fabricated as zero or scaled incorrectly.
    """
    params = urllib.parse.urlencode({
        "page": "1",
        "num": str(max(days * 3, 30)),
        "sort": "opendate",
        "asc": "0",
        "daima": _sina_market_code(symbol),
    })
    request = urllib.request.Request(
        f"{_SINA_FLOW_URL}?{params}",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn/",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8-sig"))
    if not isinstance(payload, list):
        raise RuntimeError("Sina fund-flow response is not a list")

    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        timestamp = item.get("opendate") or item.get("date")
        main = _sina_float(item.get("r0_net"))
        large = _sina_float(item.get("r1_net"))
        medium = _sina_float(item.get("r2_net"))
        small = _sina_float(item.get("r3_net"))
        overall = _sina_float(item.get("netamount"))
        if not timestamp or all(value is None for value in (main, overall, large, medium, small)):
            continue
        rows.append({
            "timestamp": str(timestamp)[:10],
            # r0_net is Sina's main-force value on this endpoint. If a
            # provider variant omits it, overall net flow is the only honest
            # value available for the normalized main field.
            "main": main if main is not None else overall,
            "small": small,
            "medium": medium,
            "large": large,
            # This endpoint does not expose a separate super-large value.
            "super_large": None,
        })
    rows.sort(key=lambda item: item.get("timestamp") or "")
    available_buckets = [
        bucket for bucket in _BUCKETS
        if any(row.get(bucket) is not None for row in rows)
    ]
    return {
        "symbol": symbol,
        "source": "sina",
        "rows": rows[-days:],
        "available_buckets": available_buckets,
        "source_note": "Sina fallback may only provide main net flow; unavailable order-size buckets are null",
    }


def _fetch_symbol_flow(symbol: str, *, period: str, days: int) -> dict[str, Any]:
    """Fetch one symbol's capital-flow series and shape it into a result dict.

    Args:
        symbol: Vibe-Trading symbol (e.g. ``"600519.SH"``, ``"AAPL.US"``).
        period: ``"daily"`` or ``"min"``.
        days: Number of most-recent daily bars to keep (ignored for ``"min"``).

    Returns:
        A per-symbol result dict carrying either ``rows`` on success or an
        ``error`` string on failure. Never raises for a single symbol.
    """
    secid = resolve_secid(symbol)
    if secid is None:
        if period == "daily":
            try:
                fallback = _fetch_sina_daily_flow(symbol, days=days)
                fallback["warning"] = "eastmoney symbol resolution failed; used sina fallback"
                return fallback
            except Exception as sina_exc:
                try:
                    fallback = tushare_fallbacks.fetch_fund_flow(symbol, days=days)
                    fallback["warning"] = "eastmoney symbol resolution failed; used tushare fallback"
                    return fallback
                except Exception as exc:  # noqa: BLE001 - fallback details belong in the symbol result
                    return {
                        "symbol": symbol,
                        "error": "unresolvable symbol",
                        "fallback_error": str(exc),
                        "sina_fallback_error": str(sina_exc),
                    }
        return {"symbol": symbol, "error": "unresolvable symbol"}

    is_daily = period == "daily"
    url = _DAILY_URL if is_daily else _MINUTE_URL
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": _DAILY_FIELDS if is_daily else _MINUTE_FIELDS,
        "klt": "101" if is_daily else "1",
        "lmt": "0" if is_daily else "0",
    }
    try:
        payload = get_json(url, params=params)
    except Exception as exc:  # noqa: BLE001 - one bad symbol must not kill the batch
        logger.warning("fund flow fetch failed for %s: %s", symbol, exc)
        if period == "daily":
            try:
                fallback = _fetch_sina_daily_flow(symbol, days=days)
                fallback["warning"] = f"eastmoney failed ({exc}); used sina fallback"
                return fallback
            except Exception as sina_exc:
                try:
                    fallback = tushare_fallbacks.fetch_fund_flow(symbol, days=days)
                    fallback["warning"] = f"eastmoney failed ({exc}); used tushare fallback"
                    return fallback
                except Exception as fallback_exc:  # noqa: BLE001 - keep per-symbol isolation
                    return {
                        "symbol": symbol,
                        "error": str(exc),
                        "fallback_error": str(fallback_exc),
                        "sina_fallback_error": str(sina_exc),
                    }
        return {"symbol": symbol, "error": str(exc)}

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {"symbol": symbol, "secid": secid, "rows": []}
    klines = data.get("klines")
    if not isinstance(klines, list):
        return {"symbol": symbol, "secid": secid, "rows": []}

    rows: list[dict[str, Any]] = []
    for raw in klines:
        if not isinstance(raw, str):
            continue
        parsed = _parse_flow_row(raw)
        if parsed is not None:
            rows.append(parsed)

    if is_daily and days < len(rows):
        rows = rows[-days:]
    if len(rows) > _MAX_ROWS_PER_SYMBOL:
        rows = rows[-_MAX_ROWS_PER_SYMBOL:]

    return {"symbol": symbol, "secid": secid, "rows": rows}


class FundFlowTool(BaseTool):
    """Fetch order-bucket net capital inflow (main/large/medium/small) for stocks."""

    name = "get_fund_flow"
    description = (
        "PER-STOCK order-level net inflow for a GIVEN symbol: for each requested "
        "ticker, the main / super-large / large / medium / small-order net inflow "
        "(in CNY), as daily history or the current session's per-minute line. Use "
        "this for one or more named stocks to gauge whether large/main-force money "
        "is flowing into or out of that specific symbol. NOT market-wide aggregate "
        "flow (for Stock-Connect 北向 use get_northbound_flow). Markets: A-share "
        "(.SH/.SZ/.BJ), Hong Kong (.HK) and US (.US). Example: "
        '{"codes": ["600519.SH", "00700.HK"], "period": "daily", "days": 30}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    'Symbols with market suffix, e.g. ["600519.SH", "000001.SZ", '
                    '"00700.HK", "AAPL.US"]. One unresolvable symbol is reported '
                    "per-symbol and does not abort the batch."
                ),
            },
            "period": {
                "type": "string",
                "enum": ["min", "daily"],
                "description": (
                    'Series granularity. "daily" = daily net-inflow history; '
                    '"min" = the current trading session per-minute line.'
                ),
                "default": "daily",
            },
            "days": {
                "type": "integer",
                "description": (
                    "For period='daily', number of most-recent daily bars to keep "
                    f"(1-{_MAX_DAYS}). Ignored for period='min'."
                ),
                "default": 30,
            },
        },
        "required": ["codes"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Resolve symbols, fetch fund flow per symbol, return a JSON envelope.

        Args:
            **kwargs: ``codes`` (list[str], required), ``period`` ("min"|"daily",
                default "daily"), ``days`` (int, default 30).

        Returns:
            A JSON string ``{"ok": true, "market": "stock", "source":
            "eastmoney", "data": {...}}`` on success, or ``{"ok": false,
            "error": ...}`` on a request-level failure.
        """
        codes = kwargs.get("codes")
        if not isinstance(codes, list) or not codes:
            return _error("codes must be a non-empty list of symbols")
        if any(not isinstance(c, str) or not c.strip() for c in codes):
            return _error("every code must be a non-empty string")

        period = kwargs.get("period", "daily")
        if period not in _VALID_PERIODS:
            return _error(f"period must be one of {list(_VALID_PERIODS)}")

        days = kwargs.get("days", 30)
        if not isinstance(days, int) or isinstance(days, bool) or days < 1:
            return _error("days must be a positive integer")
        days = min(days, _MAX_DAYS)

        results = {
            symbol: _fetch_symbol_flow(symbol, period=period, days=days)
            for symbol in (c.strip() for c in codes)
        }
        envelope = {
            "ok": True,
            "market": "stock",
            "source": "eastmoney",
            "fallback_sources": ["sina", "tushare"],
            "period": period,
            "buckets": list(_BUCKETS),
            "data": results,
        }
        return json.dumps(envelope, ensure_ascii=False)
