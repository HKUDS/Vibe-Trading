"""Southbound (Stock-Connect) market-wide net-flow tool.

Eastmoney's KAMT daily endpoint publishes the complete Shanghai/Shenzhen
Stock-Connect summary in one row.  The two Southbound legs are the
``港股通(沪)`` and ``港股通(深)`` columns.  Tushare's ``moneyflow_hsgt`` is
kept as a configured fallback because Eastmoney has intermittently returned
empty Northbound/Southbound payloads since the Stock-Connect disclosure
change.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backtest.loaders.eastmoney_client import get_json
from src.agent.tools import BaseTool
from src.tools import tushare_fallbacks
from src.tools.stock_connect_summary import SUMMARY_PARAMS, SUMMARY_URL, parse_summary

logger = logging.getLogger(__name__)

_REALTIME_URL = "https://push2.eastmoney.com/api/qt/kamt/get"
_HISTORY_URL = "https://push2his.eastmoney.com/api/qt/kamt.kline/get"
_DEFAULT_LOOKBACK_DAYS = 30
_MAX_LOOKBACK_DAYS = 250
_REALTIME_FIELDS = "f1,f2,f3,f4,f51,f52,f54,f56"
_HISTORY_FIELDS1 = "f1,f3"
_HISTORY_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57"


def _coerce_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_lookback(value: Any) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError, OverflowError):
        return _DEFAULT_LOOKBACK_DAYS
    return max(1, min(days, _MAX_LOOKBACK_DAYS))


def _parse_realtime(payload: Any) -> dict[str, float | None]:
    """Parse KAMT realtime Southbound legs when the provider exposes them."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {"shanghai_connect": None, "shenzhen_connect": None, "total": None}

    sh_block = data.get("sh2hk") if isinstance(data.get("sh2hk"), dict) else {}
    sz_block = data.get("sz2hk") if isinstance(data.get("sz2hk"), dict) else {}
    shanghai = _coerce_float(sh_block.get("netBuyAmt"))
    shenzhen = _coerce_float(sz_block.get("netBuyAmt"))
    total = None if shanghai is None and shenzhen is None else (shanghai or 0.0) + (shenzhen or 0.0)
    return {
        "shanghai_connect": shanghai,
        "shenzhen_connect": shenzhen,
        "total": total,
    }


def _parse_history_row(raw: str) -> dict[str, Any] | None:
    """Parse date, Shanghai SB, Shenzhen SB and total from a KAMT row."""
    parts = raw.split(",")
    if len(parts) < 7:
        return None
    shanghai = _coerce_float(parts[4])
    shenzhen = _coerce_float(parts[5])
    declared_total = _coerce_float(parts[6])
    if declared_total is not None:
        total = declared_total
    elif shanghai is None and shenzhen is None:
        total = None
    else:
        total = (shanghai or 0.0) + (shenzhen or 0.0)
    return {
        "trade_date": parts[0],
        "shanghai_connect": shanghai,
        "shenzhen_connect": shenzhen,
        "total": total,
    }


def _parse_history(payload: Any, lookback_days: int) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    klines = data.get("klines") if isinstance(data, dict) else None
    if not isinstance(klines, list):
        return []
    rows = [
        parsed
        for raw in klines
        if isinstance(raw, str)
        for parsed in [_parse_history_row(raw)]
        if parsed is not None
    ]
    return rows[-lookback_days:]


def _latest_as_realtime(history: list[dict[str, Any]]) -> dict[str, float | None]:
    latest = history[-1] if history else {}
    return {
        "shanghai_connect": latest.get("shanghai_connect"),
        "shenzhen_connect": latest.get("shenzhen_connect"),
        "total": latest.get("total"),
    }


class SouthboundFlowTool(BaseTool):
    """Fetch market-wide Southbound (Mainland-to-HK) net capital flow."""

    name = "get_southbound_flow"
    description = (
        "MARKET-WIDE Southbound (Stock-Connect / 南向) net capital flow for "
        "Hong Kong: Mainland capital through Shanghai-Hong Kong Connect and "
        "Shenzhen-Hong Kong Connect, as realtime/delayed latest flow plus a "
        "recent daily history. This is a market-level total, not per-stock "
        "flow. Read-only; Hong Kong Stock Connect only. Example: "
        "get_southbound_flow(lookback_days=10)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "lookback_days": {
                "type": "integer",
                "description": (
                    "Trailing trading days of Southbound history, clamped to "
                    f"1..{_MAX_LOOKBACK_DAYS}."
                ),
                "default": _DEFAULT_LOOKBACK_DAYS,
            }
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> str:
        lookback_days = _clamp_lookback(kwargs.get("lookback_days", _DEFAULT_LOOKBACK_DAYS))
        try:
            summary = parse_summary(
                get_json(SUMMARY_URL, params=SUMMARY_PARAMS),
                direction="southbound",
                lookback_days=lookback_days,
            )
        except Exception as exc:  # noqa: BLE001 - continue to independent fallback
            logger.warning("southbound mutual-quota summary failed: %s", exc)
            summary = None
        if summary is not None:
            return json.dumps(
                {
                    "ok": True,
                    "market": "Hong Kong Stock Connect",
                    "source": "eastmoney-mutual-quota",
                    "warnings": [
                        "Eastmoney mutual-quota summary provides the current daily snapshot; "
                        "historical rows require the configured Tushare fallback"
                    ],
                    "data": summary,
                },
                ensure_ascii=False,
            )
        try:
            realtime_payload = get_json(
                _REALTIME_URL,
                params={"fields": _REALTIME_FIELDS},
            )
            history_payload = get_json(
                _HISTORY_URL,
                params={
                    "fields1": _HISTORY_FIELDS1,
                    "fields2": _HISTORY_FIELDS2,
                    "klt": "101",
                    "lmt": str(_MAX_LOOKBACK_DAYS),
                },
            )
        except Exception as exc:  # noqa: BLE001 - return provider error envelope
            logger.warning("southbound flow fetch failed: %s", exc)
            return self._tushare_fallback(lookback_days, f"eastmoney failed ({exc})")

        history = _parse_history(history_payload, lookback_days)
        realtime = _parse_realtime(realtime_payload)
        # KAMT realtime fields are not consistently populated.  The latest
        # daily row is still useful, but label it as delayed rather than
        # pretending it is an intraday quote.
        if realtime.get("total") is None and history:
            realtime = _latest_as_realtime(history)
            delayed = True
        else:
            delayed = False

        if not history and realtime.get("total") is None:
            return self._tushare_fallback(
                lookback_days,
                "eastmoney returned an empty southbound-flow payload",
            )

        return json.dumps(
            {
                "ok": True,
                "market": "Hong Kong Stock Connect",
                "source": "eastmoney",
                "warnings": [
                    "latest value is delayed and comes from the last daily row"
                ]
                if delayed
                else [],
                "data": {
                    "unit": "10k CNY",
                    "lookback_days": lookback_days,
                    "realtime": realtime,
                    "history": history,
                },
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _tushare_fallback(lookback_days: int, reason: str) -> str:
        try:
            data = tushare_fallbacks.fetch_southbound_flow(lookback_days=lookback_days)
        except Exception as fallback_exc:  # noqa: BLE001 - preserve both failures
            return json.dumps(
                {
                    "ok": False,
                    "error": f"{reason}; tushare fallback failed: {fallback_exc}",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "ok": True,
                "market": "Hong Kong Stock Connect",
                "source": "tushare",
                "warnings": [f"{reason}; used tushare fallback"],
                "data": data,
            },
            ensure_ascii=False,
        )
