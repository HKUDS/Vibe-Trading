"""Northbound (Stock-Connect) net-flow tool backed by Eastmoney push2his.

Northbound flow is the net capital moving from Hong Kong into mainland China
A-shares through the Shanghai/Shenzhen Stock-Connect channels ("沪股通" and
"深股通"). Eastmoney publishes this as a free, no-auth time series through its
``push2his`` ``kamt`` (kapital-amount) endpoints. Every request routes through
the shared throttled Eastmoney client so we honor Eastmoney's per-IP rate limit
and never burst the host into a temporary ban.

This tool is read-only: it fetches the latest realtime net inflow plus a short
recent-daily history and returns them in the standard JSON envelope. It performs
no order placement and reaches no live trading endpoint.
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

# Eastmoney kamt (Stock-Connect capital) endpoints. ``kamt/get`` carries the
# realtime snapshot for both connect channels; ``kamt.kline/get`` carries the
# daily net-inflow history.
_REALTIME_URL = "https://push2.eastmoney.com/api/qt/kamt/get"
_HISTORY_URL = "https://push2his.eastmoney.com/api/qt/kamt.kline/get"

# Default and ceiling for the recent-daily window. The history endpoint returns
# at most a few years of daily points; we cap to keep the payload bounded.
_DEFAULT_LOOKBACK_DAYS = 30
_MAX_LOOKBACK_DAYS = 250

# Realtime snapshot field selectors. Eastmoney's kamt realtime payload nests the
# two channels under ``data`` with ``s2n`` (south-to-north net inflow) figures
# per channel: ``hk2sh`` (Shanghai-Connect) and ``hk2sz`` (Shenzhen-Connect).
_REALTIME_FIELDS = "f1,f2,f3,f4,f51,f52,f54,f56"

# History field selectors.  Eastmoney's KAMT row is a compact Stock-Connect
# summary, not a three-column northbound-only series:
#
#   f51 date, f52 Shanghai NB, f53 Shenzhen NB, f54 Northbound total,
#   f55 Shanghai SB, f56 Shenzhen SB, f57 Southbound total.
#
# The old implementation requested only f51/f52/f54 and then interpreted the
# third cell as Shenzhen NB.  That silently turned Northbound total into the
# Shenzhen leg and made the Southbound series impossible to retrieve.
_HISTORY_FIELDS1 = "f1,f3"
_HISTORY_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57"


def _coerce_float(value: Any) -> float | None:
    """Coerce a raw Eastmoney numeric cell to ``float`` or ``None``.

    Args:
        value: Raw value from the payload (number, numeric string, or sentinel).

    Returns:
        The parsed float, or ``None`` when the cell is missing or not numeric
        (Eastmoney uses ``"-"`` for an absent figure).
    """
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_realtime(payload: Any) -> dict[str, float | None]:
    """Extract per-channel realtime net inflow from a kamt realtime payload.

    Args:
        payload: Decoded JSON from :data:`_REALTIME_URL`.

    Returns:
        Mapping with ``shanghai_connect``, ``shenzhen_connect`` and ``total``
        net inflow (10k CNY); each value is ``None`` when unavailable.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {"shanghai_connect": None, "shenzhen_connect": None, "total": None}

    sh_block = data.get("hk2sh") if isinstance(data.get("hk2sh"), dict) else {}
    sz_block = data.get("hk2sz") if isinstance(data.get("hk2sz"), dict) else {}

    shanghai = _coerce_float(sh_block.get("netBuyAmt"))
    shenzhen = _coerce_float(sz_block.get("netBuyAmt"))
    total: float | None
    if shanghai is None and shenzhen is None:
        total = None
    else:
        total = (shanghai or 0.0) + (shenzhen or 0.0)

    return {
        "shanghai_connect": shanghai,
        "shenzhen_connect": shenzhen,
        "total": total,
    }


def _parse_history_row(raw: str) -> dict[str, Any] | None:
    """Parse one ``kamt.kline`` history row into a daily net-inflow dict.

    Column order follows :data:`_HISTORY_FIELDS2`.  For compatibility with
    mocked/legacy three-cell rows, a three-cell row is still interpreted as
    date, Shanghai, Shenzhen.  Real KAMT rows are parsed by the seven-cell
    layout documented above.

    Args:
        raw: One comma-joined row string from ``data.klines``.

    Returns:
        A dict ``{trade_date, shanghai_connect, shenzhen_connect, total}``, or
        ``None`` when the row is malformed.
    """
    parts = raw.split(",")
    if len(parts) < 3:
        return None
    shanghai = _coerce_float(parts[1])
    shenzhen = _coerce_float(parts[2])
    declared_total = _coerce_float(parts[3]) if len(parts) >= 7 else None
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
    """Extract the most recent ``lookback_days`` daily net-inflow rows.

    Args:
        payload: Decoded JSON from :data:`_HISTORY_URL`.
        lookback_days: Number of trailing daily rows to keep.

    Returns:
        Ascending list of daily net-inflow dicts (empty when no rows).
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    klines = data.get("klines")
    if not isinstance(klines, list):
        return []

    rows: list[dict[str, Any]] = []
    for raw in klines:
        if not isinstance(raw, str):
            continue
        parsed = _parse_history_row(raw)
        if parsed is not None:
            rows.append(parsed)
    return rows[-lookback_days:]


def _clamp_lookback(value: Any) -> int:
    """Clamp a requested lookback to ``[1, _MAX_LOOKBACK_DAYS]``.

    Args:
        value: Raw ``lookback_days`` argument (any type the caller supplied).

    Returns:
        A valid lookback day count, defaulting on unparseable input.
    """
    try:
        days = int(value)
    except (TypeError, ValueError, OverflowError):
        return _DEFAULT_LOOKBACK_DAYS
    if days < 1:
        return 1
    if days > _MAX_LOOKBACK_DAYS:
        return _MAX_LOOKBACK_DAYS
    return days


class NorthboundFlowTool(BaseTool):
    """Fetch Northbound (Stock-Connect) net capital flow from Eastmoney."""

    name = "get_northbound_flow"
    description = (
        "MARKET-WIDE Northbound (Stock-Connect / 北向) net capital flow for the "
        "whole mainland China A-share market: the aggregate net inflow from Hong "
        "Kong, split into Shanghai-Connect (沪股通) and Shenzhen-Connect (深股通) "
        "channels (units: 10k CNY), as the latest realtime figure plus a recent "
        "daily history. This is a market-level total, NOT per-stock flow (for a "
        "given symbol's order-bucket inflow use get_fund_flow). Read-only; China "
        "A-share market only. Example: get_northbound_flow(lookback_days=10)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "lookback_days": {
                "type": "integer",
                "description": (
                    "Number of trailing trading days of daily net-inflow history "
                    f"to return, clamped to 1..{_MAX_LOOKBACK_DAYS}."
                ),
                "default": _DEFAULT_LOOKBACK_DAYS,
            },
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> str:
        """Fetch realtime + recent-daily Northbound net flow as a JSON envelope.

        Args:
            **kwargs: Accepts ``lookback_days`` (int, default
                :data:`_DEFAULT_LOOKBACK_DAYS`).

        Returns:
            A JSON string envelope ``{"ok": true, "market": "China A",
            "source": "eastmoney", "data": {...}}`` on success, or
            ``{"ok": false, "error": str}`` on failure.
        """
        lookback_days = _clamp_lookback(kwargs.get("lookback_days", _DEFAULT_LOOKBACK_DAYS))

        # The mutual-quota report is the current Eastmoney contract for the
        # four Stock-Connect legs.  It is more reliable than guessing the
        # shape of the older KAMT endpoint and gives us a real current value
        # even when the optional minute series is empty.
        try:
            summary = parse_summary(
                get_json(SUMMARY_URL, params=SUMMARY_PARAMS),
                direction="northbound",
                lookback_days=lookback_days,
            )
        except Exception as exc:  # noqa: BLE001 - continue to independent fallback
            logger.warning("northbound mutual-quota summary failed: %s", exc)
            summary = None
        if summary is not None:
            return json.dumps(
                {
                    "ok": True,
                    "market": "China A",
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
        except Exception as exc:  # noqa: BLE001 - surface as error envelope
            logger.warning("northbound flow fetch failed: %s", exc)
            try:
                fallback_data = tushare_fallbacks.fetch_northbound_flow(
                    lookback_days=lookback_days
                )
            except Exception as fallback_exc:  # noqa: BLE001 - return both provider failures
                return json.dumps(
                    {
                        "ok": False,
                        "error": f"{exc}; tushare fallback failed: {fallback_exc}",
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "ok": True,
                    "market": "China A",
                    "source": "tushare",
                    "warnings": [
                        "eastmoney failed "
                        f"({exc}); used tushare fallback with latest daily data"
                    ],
                    "data": fallback_data,
                },
                ensure_ascii=False,
            )

        realtime = _parse_realtime(realtime_payload)
        history = _parse_history(history_payload, lookback_days)

        # Eastmoney can return HTTP 200 with an empty/placeholder payload while
        # the endpoint is degraded. Treat that as unavailable and try the
        # configured Tushare adapter instead of presenting green-check nulls.
        if not history and realtime.get("total") is None:
            try:
                fallback_data = tushare_fallbacks.fetch_northbound_flow(
                    lookback_days=lookback_days
                )
            except Exception as fallback_exc:  # noqa: BLE001 - report both causes
                return json.dumps(
                    {
                        "ok": False,
                        "error": (
                            "eastmoney returned no northbound-flow data; "
                            f"tushare fallback failed: {fallback_exc}"
                        ),
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "ok": True,
                    "market": "China A",
                    "source": "tushare",
                    "warnings": [
                        "eastmoney returned an empty northbound-flow payload; "
                        "used tushare fallback"
                    ],
                    "data": fallback_data,
                },
                ensure_ascii=False,
            )

        envelope = {
            "ok": True,
            "market": "China A",
            "source": "eastmoney",
            "data": {
                "unit": "10k CNY",
                "lookback_days": lookback_days,
                "realtime": realtime,
                "history": history,
            },
        }
        return json.dumps(envelope, ensure_ascii=False)
