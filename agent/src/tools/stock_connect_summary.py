"""Parsing helpers for Eastmoney's Stock-Connect market summary."""

from __future__ import annotations

from typing import Any

SUMMARY_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
SUMMARY_PARAMS = {
    "reportName": "RPT_MUTUAL_QUOTA",
    "columns": (
        "TRADE_DATE,MUTUAL_TYPE,BOARD_TYPE,MUTUAL_TYPE_NAME,FUNDS_DIRECTION,"
        "INDEX_CODE,INDEX_NAME,BOARD_CODE"
    ),
    "quoteColumns": (
        "status~07~BOARD_CODE,dayNetAmtIn~07~BOARD_CODE,"
        "dayAmtRemain~07~BOARD_CODE,dayAmtThreshold~07~BOARD_CODE,"
        "f104~07~BOARD_CODE,f105~07~BOARD_CODE,f106~07~BOARD_CODE,"
        "f3~03~INDEX_CODE~INDEX_f3,netBuyAmt~07~BOARD_CODE"
    ),
    "quoteType": "0",
    "pageNumber": "1",
    "pageSize": "2000",
    "sortTypes": "1",
    "sortColumns": "MUTUAL_TYPE",
    "source": "WEB",
    "client": "WEB",
}

_TYPE_BY_DIRECTION = {
    "northbound": {"001": "shanghai_connect", "003": "shenzhen_connect"},
    "southbound": {"002": "shanghai_connect", "004": "shenzhen_connect"},
}


def _float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_summary(
    payload: Any,
    *,
    direction: str,
    lookback_days: int,
) -> dict[str, Any] | None:
    """Normalize the current four-row Eastmoney summary.

    ``netBuyAmt`` is published in ten-thousand CNY units by this endpoint,
    matching the Stock-Connect tool envelope.  A result with rows but missing
    numeric values is rejected so callers can use the Tushare fallback.
    """
    type_map = _TYPE_BY_DIRECTION.get(direction)
    if not type_map:
        raise ValueError(f"unsupported Stock-Connect direction: {direction}")
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = result.get("data") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        return None

    legs: dict[str, float | None] = {
        "shanghai_connect": None,
        "shenzhen_connect": None,
    }
    trade_date: str | None = None
    found_numeric = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        leg = type_map.get(str(row.get("MUTUAL_TYPE") or "").strip())
        if leg is None:
            continue
        if trade_date is None and row.get("TRADE_DATE"):
            trade_date = str(row["TRADE_DATE"])[:10]
        value = _float(row.get("netBuyAmt"))
        if value is not None:
            legs[leg] = value
            found_numeric = True

    if not found_numeric:
        return None
    total = sum(value for value in legs.values() if value is not None)
    row = {
        "trade_date": trade_date,
        **legs,
        "total": total,
    }
    return {
        "unit": "10k CNY",
        "lookback_days": min(lookback_days, 1),
        "realtime": {
            "shanghai_connect": legs["shanghai_connect"],
            "shenzhen_connect": legs["shenzhen_connect"],
            "total": total,
        },
        "history": [row],
    }

