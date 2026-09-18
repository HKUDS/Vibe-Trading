"""Southbound (Stock-Connect) net capital flow tool.

Southbound flow is the net capital moving from mainland China into
Hong Kong equities through the 港股通（沪）/ 港股通（深） channels. Since the
2024-08-30 HKEX disclosure reform ended northbound daily net-buy
publishing (#1481), southbound is the only Stock-Connect direction whose
daily net buy is still officially disclosed — HKEX publishes per-channel
Buy/Sell Turnover every trading day, and Eastmoney's datacenter series
cross-checks against it exactly (#1483).

Sources, in order:

* **Eastmoney datacenter** ``RPT_MUTUAL_DEAL_HISTORY`` (``MUTUAL_TYPE``
  ``002`` = 港股通沪, ``004`` = 港股通深) through the shared throttled
  client: daily net buy (``NET_DEAL_AMT``), buy/sell turnover and the
  cumulative net series, unit 100M HKD (亿). Verified against HKEX
  official daily statistics to the cent on 2026-09-15/16/17.
* **HKEX official** Stock Connect Daily Statistics report (keyless JS
  feed): latest available trading day only, net = Buy Turnover − Sell
  Turnover per channel, converted from million HKD to the envelope unit.

There is deliberately **no tushare path**: ``moneyflow_hsgt``'s
southbound fields (``ggt_ss``/``ggt_sz``/``south_money``) now carry the
*cumulative* net-bought stock, not daily flow — ``ggt_ss`` equals
Eastmoney's ``ACCUM_DEAL_AMT`` exactly and moves ~0.4% across a six-week
window (#1483) — so serving them as flow would mislabel a stock as a
rate.

This tool is read-only: it places no orders and reaches no live trading
endpoint.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

import requests

from backtest.loaders import eastmoney_client
from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)

# Eastmoney datacenter report carrying the Stock-Connect daily history.
# MUTUAL_TYPE: "002" = 港股通（沪）, "004" = 港股通（深）. Amounts are in
# 100M HKD (亿); NET_DEAL_AMT cross-checks against HKEX Buy − Sell exactly.
_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_REPORT_NAME = "RPT_MUTUAL_DEAL_HISTORY"
_CHANNEL_TYPES = {"shanghai_connect": "002", "shenzhen_connect": "004"}

# HKEX official daily statistics (keyless). One JS file per trading day;
# the southbound sections carry Buy/Sell Turnover in million HKD.
_HKEX_DAILY_URL = "https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_{date}e.js"
_HKEX_WALKBACK_DAYS = 7
_HKEX_TIMEOUT_S = 12
_HKEX_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; vibe-trading)"}

_DEFAULT_LOOKBACK_DAYS = 30
_MAX_LOOKBACK_DAYS = 250

_NOTE = (
    "Southbound daily net buy is still officially disclosed (HKEX Buy/Sell "
    "Turnover); tushare moneyflow_hsgt southbound fields are NOT used here: "
    "they drifted to cumulative net-bought stock, not daily flow (#1483)."
)


def _coerce_float(value: Any) -> float | None:
    """Coerce a raw provider cell to ``float``, ``None`` on missing/garbage."""
    if value in (None, "", "-", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trade_date(raw: Any) -> str | None:
    """Normalize an Eastmoney ``TRADE_DATE`` cell to ``YYYY-MM-DD``."""
    text = str(raw or "").strip()
    return text[:10] if len(text) >= 10 else None


def _clamp_lookback(value: Any) -> int:
    """Clamp a requested lookback to ``[1, _MAX_LOOKBACK_DAYS]``."""
    try:
        days = int(value)
    except (TypeError, ValueError, OverflowError):
        return _DEFAULT_LOOKBACK_DAYS
    return max(1, min(days, _MAX_LOOKBACK_DAYS))


def _fetch_eastmoney_channel(mutual_type: str, days: int) -> list[dict[str, Any]]:
    """Fetch one 港股通 channel's daily rows, newest first.

    Args:
        mutual_type: Eastmoney ``MUTUAL_TYPE`` code ("002" or "004").
        days: Number of trailing trading days to request.

    Returns:
        Raw datacenter rows (possibly empty).

    Raises:
        Exception: Network/decoding failures propagate for the caller's
            fallback policy.
    """
    payload = eastmoney_client.get_json(
        _DATACENTER_URL,
        params={
            "reportName": _REPORT_NAME,
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "filter": f'(MUTUAL_TYPE="{mutual_type}")',
            "sortColumns": "TRADE_DATE",
            "sortTypes": "-1",
            "pageNumber": "1",
            "pageSize": str(days),
        },
    )
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = result.get("data") if isinstance(result, dict) else None
    return rows if isinstance(rows, list) else []


def _merge_eastmoney(days: int) -> list[dict[str, Any]]:
    """Fetch both 港股通 channels and merge them into ascending daily rows.

    Args:
        days: Trailing trading days per channel.

    Returns:
        Ascending list of ``{trade_date, shanghai_connect, shenzhen_connect,
        total}`` dicts (net buy, 100M HKD). Empty when neither channel
        serves rows.
    """
    per_channel: dict[str, dict[str, float | None]] = {}
    for key, mutual_type in _CHANNEL_TYPES.items():
        for row in _fetch_eastmoney_channel(mutual_type, days):
            date = _trade_date(row.get("TRADE_DATE"))
            if date is None:
                continue
            net = _coerce_float(row.get("NET_DEAL_AMT"))
            per_channel.setdefault(date, {})[key] = (
                round(net, 4) if net is not None else None
            )
    history: list[dict[str, Any]] = []
    for date in sorted(per_channel):
        entry = per_channel[date]
        shanghai = entry.get("shanghai_connect")
        shenzhen = entry.get("shenzhen_connect")
        values = [v for v in (shanghai, shenzhen) if v is not None]
        history.append(
            {
                "trade_date": date,
                "shanghai_connect": shanghai,
                "shenzhen_connect": shenzhen,
                "total": round(sum(values), 4) if values else None,
            }
        )
    return history[-days:]


def _parse_hkex_report(text: str) -> dict[str, Any] | None:
    """Extract southbound nets from one HKEX daily-statistics JS payload.

    Args:
        text: Raw ``data_tab_daily_<date>e.js`` body (``tabData = [...]``).

    Returns:
        ``{trade_date, shanghai_connect, shenzhen_connect, total}`` in 100M
        HKD, or ``None`` when the southbound sections are absent.
    """
    try:
        payload = json.loads(text[text.index("[") : text.rindex("]") + 1])
    except (ValueError, json.JSONDecodeError):
        return None
    nets: dict[str, float] = {}
    date: str | None = None
    for section in payload if isinstance(payload, list) else []:
        market = section.get("market")
        if market not in ("SSE Southbound", "SZSE Southbound"):
            continue
        date = date or section.get("date")
        for content in section.get("content", []):
            table = content.get("table", {})
            schema = (table.get("schema") or [[]])[0]
            # The aggregate summary table is the one led by Total Turnover
            # with one metric per row. The section's second table (top-10
            # stocks) also carries Buy/Sell Turnover columns but one row per
            # stock — it must not be mistaken for the summary.
            if not schema or schema[0] != "Total Turnover":
                continue
            if "Buy Turnover" not in schema or "Sell Turnover" not in schema:
                continue
            cells: list[str] = []
            for row in table.get("tr", []):
                for cell in row.get("td", []):
                    cells.append(cell[0] if isinstance(cell, list) else cell)
            values = dict(zip(schema, cells))
            buy = _coerce_float(str(values.get("Buy Turnover", "")).replace(",", ""))
            sell = _coerce_float(str(values.get("Sell Turnover", "")).replace(",", ""))
            if buy is not None and sell is not None:
                # million HKD → 100M HKD to match the Eastmoney caliber.
                nets[market] = round((buy - sell) / 100.0, 4)
            break
    if not nets:
        return None
    shanghai = nets.get("SSE Southbound")
    shenzhen = nets.get("SZSE Southbound")
    values = [v for v in (shanghai, shenzhen) if v is not None]
    return {
        "trade_date": date,
        "shanghai_connect": shanghai,
        "shenzhen_connect": shenzhen,
        "total": round(sum(values), 4) if values else None,
    }


def _fetch_hkex_latest() -> dict[str, Any] | None:
    """Walk back up to a week for the latest HKEX daily-statistics report.

    Returns:
        The parsed southbound snapshot row, or ``None`` when no trading
        day within the walkback window serves a usable report.
    """
    today = dt.date.today()
    for offset in range(_HKEX_WALKBACK_DAYS + 1):
        day = today - dt.timedelta(days=offset)
        url = _HKEX_DAILY_URL.format(date=day.strftime("%Y%m%d"))
        try:
            response = requests.get(url, timeout=_HKEX_TIMEOUT_S, headers=_HKEX_HEADERS)
        except requests.RequestException as exc:
            logger.debug("HKEX daily statistics unreachable for %s: %s", day, exc)
            return None
        if response.status_code == 404:
            continue  # weekend / holiday / not yet published
        if response.status_code != 200:
            logger.debug(
                "HKEX daily statistics HTTP %s for %s", response.status_code, day
            )
            continue
        row = _parse_hkex_report(response.text)
        if row is not None:
            return row
    return None


class SouthboundFlowTool(BaseTool):
    """Fetch Southbound (Stock-Connect) net capital flow into Hong Kong."""

    name = "get_southbound_flow"
    description = (
        "MARKET-WIDE Southbound (Stock-Connect / 南向) net capital flow for "
        "the whole Hong Kong market: the aggregate daily net buy from the "
        "mainland through the 港股通（沪） and 港股通（深） channels (units: "
        "100M HKD, 亿), as the latest trading day plus a recent daily "
        "history. Southbound is the only Stock-Connect direction whose daily "
        "net buy is still officially disclosed (HKEX; the northbound net "
        "ended 2024-08-30 — see get_northbound_flow). This is a market-level "
        "total, NOT per-stock flow (for a given symbol's order-bucket inflow "
        "use get_fund_flow). Read-only. Example: "
        "get_southbound_flow(lookback_days=10)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "lookback_days": {
                "type": "integer",
                "description": (
                    "Number of trailing trading days of daily net-buy history "
                    f"to return, clamped to 1..{_MAX_LOOKBACK_DAYS}."
                ),
                "default": _DEFAULT_LOOKBACK_DAYS,
            },
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> str:
        """Fetch latest + recent-daily Southbound net flow as a JSON envelope.

        Args:
            **kwargs: Accepts ``lookback_days`` (int, default
                :data:`_DEFAULT_LOOKBACK_DAYS`).

        Returns:
            A JSON string envelope ``{"ok": true, "market": "HK",
            "source": "eastmoney"|"hkex", "data": {...}}`` on success, or
            ``{"ok": false, "error": str}`` when neither source serves data.
        """
        lookback_days = _clamp_lookback(
            kwargs.get("lookback_days", _DEFAULT_LOOKBACK_DAYS)
        )

        history: list[dict[str, Any]] = []
        eastmoney_error: str | None = None
        try:
            history = _merge_eastmoney(lookback_days)
        except Exception as exc:  # noqa: BLE001 - fall back to HKEX official
            eastmoney_error = str(exc)
            logger.warning("southbound eastmoney fetch failed: %s", exc)

        if history:
            latest = history[-1]
            return json.dumps(
                {
                    "ok": True,
                    "market": "HK",
                    "source": "eastmoney",
                    "data": {
                        "unit": "100M HKD",
                        "lookback_days": lookback_days,
                        "note": _NOTE,
                        "realtime": latest,
                        "history": history,
                    },
                },
                ensure_ascii=False,
            )

        snapshot = _fetch_hkex_latest()
        if snapshot is not None:
            reason = (
                f"eastmoney datacenter unavailable ({eastmoney_error})"
                if eastmoney_error
                else "eastmoney datacenter returned no rows"
            )
            return json.dumps(
                {
                    "ok": True,
                    "market": "HK",
                    "source": "hkex",
                    "warnings": [
                        f"{reason}; used the HKEX official daily statistics — "
                        "latest trading day snapshot only"
                    ],
                    "data": {
                        "unit": "100M HKD",
                        "lookback_days": lookback_days,
                        "note": _NOTE,
                        "realtime": snapshot,
                        "history": [snapshot],
                    },
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "ok": False,
                "error": (
                    "southbound flow unavailable: eastmoney datacenter "
                    f"({'failed: ' + eastmoney_error if eastmoney_error else 'empty'})"
                    "; HKEX official daily statistics unavailable"
                ),
            },
            ensure_ascii=False,
        )
