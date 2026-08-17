"""A-share data adapters sourced from the ``a-stock-data`` skill.

This module keeps the provider-specific endpoints in one place so the agent
tools do not need to know about Tencent's GBK payloads, Eastmoney JSONP, Sina's
report-list shape, or CNINFO's issuer identifiers.  It is deliberately
additive: the existing loader/tool stack remains the default for existing
features, while :mod:`src.tools.a_share_data_tool` exposes these richer
read-only A-share surfaces.

Provider routing follows a-stock-data's low-friction path:

* Tencent: quote snapshots and daily adjusted bars;
* Eastmoney: sell-side reports, stock news, global fast news, and profile data;
* Cailianpress: independent global flash-news fallback;
* Sina: quarterly income/balance/cash-flow statements;
* CNINFO: listed-company announcements.

All Eastmoney GETs use the repository's shared host throttle.  Inputs are
strictly normalized before reaching a provider so malformed or contradictory
market identifiers fail loudly rather than returning another security's data.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from typing import Any

import pandas as pd
import requests

from backtest.loaders._http import (
    DEFAULT_USER_AGENT,
    resolve_min_interval,
    throttled_get,
)

logger = logging.getLogger(__name__)

_UA = DEFAULT_USER_AGENT
_EM_REPORT_URL = "https://reportapi.eastmoney.com/report/list"
_EM_SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"
_EM_FAST_NEWS_URL = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
_EM_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
_EM_BOARD_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
_EM_BOARD_MEMBERSHIP_URL = "https://push2.eastmoney.com/api/qt/slist/get"
_TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
_TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_TENCENT_MINUTE_KLINE_URL = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"
_THS_KLINE_URL = "https://d.10jqka.com.cn/v6/line/hs_{code}/{period}/last36000.js"
_SINA_FINANCE_URL = (
    "https://quotes.sina.cn/cn/api/openapi.php/"
    "CompanyFinanceService.getFinanceReport2022"
)
_SINA_STOCK_NEWS_URL = "https://zhibo.sina.com.cn/api/zhibo/feed"
_CNINFO_MAP_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
_CNINFO_ANN_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
_CLS_ROLL_URL = "https://www.cls.cn/v1/roll/get_roll_list"

_EM_MIN_INTERVAL_ENV = "VIBE_TRADING_EASTMONEY_MIN_INTERVAL"
_EM_DEFAULT_MIN_INTERVAL = 1.0
_TENCENT_MIN_INTERVAL_ENV = "VIBE_TRADING_TENCENT_MIN_INTERVAL"
_TENCENT_DEFAULT_MIN_INTERVAL = 0.15
_SINA_MIN_INTERVAL_ENV = "VIBE_TRADING_SINA_MIN_INTERVAL"
_SINA_DEFAULT_MIN_INTERVAL = 0.5
_CNINFO_MIN_INTERVAL_ENV = "VIBE_TRADING_CNINFO_MIN_INTERVAL"
_CNINFO_DEFAULT_MIN_INTERVAL = 0.5
_STOCK_CONTENT_LOOKBACK_DAYS = 365

_TICKER_RE = re.compile(
    r"^(?:(sh|sz|bj)(\d{6})|(\d{6})(?:\.(sh|sz|bj))?)$",
    re.IGNORECASE,
)
_SH_INDEX_CODES = {"000001", "000016", "000010", "000016", "000300", "000852", "000905"}

_CNINFO_ORGID_MAP: dict[str, str] = {}
_CNINFO_MAP_LOCK = threading.Lock()


def _natural_market(digits: str) -> str:
    if digits.startswith("92") or digits[:2] in {"43", "83", "87"}:
        return "BJ"
    if digits[0] in {"5", "6", "9"}:
        return "SH"
    if digits.startswith("4") or digits.startswith("8"):
        return "BJ"
    return "SZ"


def normalize_a_share_code(value: str, *, stock_only: bool = False) -> tuple[str, str]:
    """Return ``(bare_code, exchange)`` for a strict A-share identifier.

    Accepted forms are ``600519``, ``SH600519``, ``600519.SH`` and their SZ/BJ
    equivalents.  A bare ``000xxx`` is treated as a Shenzhen security; an
    explicit ``SH`` suffix is retained for index quote requests but rejected by
    stock-only endpoints because Shanghai has no 000xxx listed stock.
    """
    raw = str(value or "").strip()
    match = _TICKER_RE.fullmatch(raw)
    if not match:
        raise ValueError(
            f"invalid A-share code {value!r}; expected 600519, SH600519, or 600519.SH"
        )
    digits = match.group(2) or match.group(3)
    explicit = (match.group(1) or match.group(4) or "").upper()
    market = explicit or _natural_market(digits)
    if explicit:
        if digits.startswith("000"):
            if explicit == "BJ":
                raise ValueError(f"{value!r} has an invalid BJ market for 000xxx")
            if stock_only and explicit == "SH":
                raise ValueError(f"{value!r} is an index-style SH000xxx code, not an A-share stock")
        elif explicit != _natural_market(digits):
            raise ValueError(
                f"{value!r} market conflicts with code {digits}; expected {_natural_market(digits)}"
            )
    if stock_only and digits in _SH_INDEX_CODES and market == "SH" and digits.startswith("000"):
        raise ValueError(f"{value!r} is an index-style code, not an A-share stock")
    return digits, market


def canonical_a_share_code(value: str, *, stock_only: bool = False) -> str:
    digits, market = normalize_a_share_code(value, stock_only=stock_only)
    return f"{digits}.{market}"


def _market_prefix(digits: str, market: str) -> str:
    return market.lower() + digits


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-", "--"):
            return default
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _normalize_tencent_bar_time(value: Any) -> str:
    """Normalize Tencent's compact intraday timestamp for the chart API."""
    text = str(value or "")
    if re.fullmatch(r"\d{12}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]} {text[8:10]}:{text[10:12]}"
    return text


def _em_get(url: str, *, params: dict[str, Any], headers: dict[str, str] | None = None, timeout: float = 15.0) -> requests.Response:
    response = throttled_get(
        url,
        host_key="eastmoney",
        min_interval=resolve_min_interval(_EM_MIN_INTERVAL_ENV, _EM_DEFAULT_MIN_INTERVAL),
        params=params,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return response


def _provider_get(
    url: str,
    *,
    host_key: str,
    min_interval_env: str,
    default_interval: float,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> requests.Response:
    response = throttled_get(
        url,
        host_key=host_key,
        min_interval=resolve_min_interval(min_interval_env, default_interval),
        params=params,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return response


def _parse_jsonp(text: str) -> Any:
    raw = text.strip()
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        start, end = raw.find("("), raw.rfind(")")
        if start < 0 or end <= start:
            raise ValueError("provider returned neither JSON nor JSONP")
        return json.loads(raw[start + 1 : end])


def tencent_quote(codes: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch Tencent real-time quote/valuation fields for A-share symbols."""
    if not codes:
        return {}
    prefixed: list[str] = []
    key_of: dict[str, str] = {}
    for raw in codes:
        digits, market = normalize_a_share_code(raw)
        provider_key = _market_prefix(digits, market)
        prefixed.append(provider_key)
        key_of[provider_key] = canonical_a_share_code(raw)
    response = _provider_get(
        _TENCENT_QUOTE_URL + ",".join(prefixed),
        host_key="tencent",
        min_interval_env=_TENCENT_MIN_INTERVAL_ENV,
        default_interval=_TENCENT_DEFAULT_MIN_INTERVAL,
        headers={"Referer": "https://gu.qq.com/"},
        timeout=10,
    )
    text = response.content.decode("gbk", errors="replace")
    result: dict[str, dict[str, Any]] = {}
    for line in text.split(";"):
        if "=" not in line or '"' not in line:
            continue
        provider_key = line.split("=", 1)[0].split("_")[-1].lower()
        values = line.split('"', 2)[1].split("~")
        if len(values) < 53:
            continue
        code = key_of.get(provider_key, provider_key[2:].upper())
        record = {
            "code": code,
            "name": values[1],
            "price": _number(values[3]),
            "last_close": _number(values[4]),
            "open": _number(values[5]),
            "change_amt": _number(values[31]),
            "change_pct": _number(values[32]),
            "high": _number(values[33]),
            "low": _number(values[34]),
            "amount_wan": _number(values[37]),
            "turnover_pct": _number(values[38]),
            "pe_ttm": _number(values[39]),
            "amplitude_pct": _number(values[43]),
            "float_mcap_yi": _number(values[44]),
            "mcap_yi": _number(values[45]),
            "pb": _number(values[46]),
            "limit_up": _number(values[47]),
            "limit_down": _number(values[48]),
            "vol_ratio": _number(values[49]),
            "pe_static": _number(values[52]),
        }
        record["is_stale"] = bool(
            record["amount_wan"] == 0
            and record["price"] == record["last_close"]
            and record["price"] > 0
        )
        if record["is_stale"]:
            record["stale_reason"] = "成交量为 0（停牌/未开盘/废码），报价非当日真实成交"
        result[code] = record
    return result


def _aggregate_bars(bars: list[dict[str, Any]], factor: int) -> list[dict[str, Any]]:
    """Aggregate intraday bars without crossing trading sessions."""
    if factor <= 1:
        return bars
    output: list[dict[str, Any]] = []
    bucket: list[dict[str, Any]] = []
    session = ""

    def flush() -> None:
        if not bucket:
            return
        output.append({
            "trade_date": bucket[0]["trade_date"],
            "open": bucket[0]["open"],
            "close": bucket[-1]["close"],
            "high": max(item["high"] for item in bucket),
            "low": min(item["low"] for item in bucket),
            "volume": sum(item["volume"] or 0 for item in bucket),
            "source": "tencent",
        })

    for bar in bars:
        current_session = str(bar.get("trade_date", ""))[:10]
        if session and current_session != session:
            flush()
            bucket = []
        session = current_session
        bucket.append(bar)
        if len(bucket) >= factor:
            flush()
            bucket = []
    flush()
    return output


def tencent_bars(
    code: str,
    start_date: str,
    end_date: str,
    period: str = "1d",
) -> list[dict[str, Any]]:
    """Fetch forward-adjusted A-share OHLCV bars for the requested period."""
    period_key = str(period or "1d").strip().lower()
    provider_period = {
        "1d": "day", "1w": "week", "1mo": "month",
        "1m": "m1", "15m": "m15", "30m": "m30", "60m": "m60", "120m": "m60",
    }.get(period_key)
    if provider_period is None:
        raise ValueError(f"unsupported A-share bar period: {period}")
    digits, market = normalize_a_share_code(code, stock_only=True)
    provider_key = _market_prefix(digits, market)
    if period_key in {"1m", "15m", "30m", "60m", "120m"}:
        # Tencent serves intraday bars from a different endpoint.  Sending
        # m1/m15/... to fqkline/get returns a successful response with no
        # matching qfq* series, which used to make the stock detail chart
        # silently render an empty dataset.
        response = _provider_get(
            _TENCENT_MINUTE_KLINE_URL,
            host_key="tencent",
            min_interval_env=_TENCENT_MIN_INTERVAL_ENV,
            default_interval=_TENCENT_DEFAULT_MIN_INTERVAL,
            params={"param": f"{provider_key},{provider_period},,320"},
            headers={"Referer": "https://gu.qq.com/"},
            timeout=15,
        )
    else:
        response = _provider_get(
            _TENCENT_KLINE_URL,
            host_key="tencent",
            min_interval_env=_TENCENT_MIN_INTERVAL_ENV,
            default_interval=_TENCENT_DEFAULT_MIN_INTERVAL,
            params={"param": f"{provider_key},{provider_period},{start_date},{end_date},500,qfq"},
            headers={"Referer": "https://web.ifzq.gtimg.cn/"},
            timeout=15,
        )
    payload = response.json()
    data = payload.get("data") or {}
    item = data.get(provider_key) or next(iter(data.values()), {})
    rows = item.get(f"qfq{provider_period}") or item.get(provider_period) or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        out.append({
            "trade_date": _normalize_tencent_bar_time(row[0]),
            "open": _number(row[1]),
            "close": _number(row[2]),
            "high": _number(row[3]),
            "low": _number(row[4]),
            "volume": _number(row[5]),
            "source": "tencent",
        })
    if period_key in {"1m", "15m", "30m", "60m", "120m"} and out:
        # The minute endpoint returns a rolling window (up to 320 bars), so
        # it can contain the previous session as well as today's session.
        # A-share detail's intraday view is explicitly one trading day.
        latest_day = max(str(item["trade_date"])[:10] for item in out)
        out = [item for item in out if str(item["trade_date"])[:10] == latest_day]
    return _aggregate_bars(out, 2 if period_key == "120m" else 1)


def _normalize_ths_bar_time(value: Any) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{12}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]} {text[8:10]}:{text[10:12]}"
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text.replace("T", " ")[:19]


def ths_bars(
    code: str,
    start_date: str,
    end_date: str,
    period: str = "30m",
) -> list[dict[str, Any]]:
    """Fetch historical A-share intraday bars from Tonghuashun.

    Tencent's minute endpoint is a rolling current-session feed.  THS's
    ``last36000`` line endpoint is the historical source used for 15/30/60m;
    callers can aggregate 60m bars for a 120m view without falling back to a
    current-day-only dataset.
    """
    period_key = str(period or "30m").strip().lower()
    provider_period = {"15m": "15", "30m": "30", "60m": "60"}.get(period_key)
    if provider_period is None:
        raise ValueError(f"unsupported THS intraday bar period: {period}")
    digits, _ = normalize_a_share_code(code, stock_only=True)
    response = _provider_get(
        _THS_KLINE_URL.format(code=digits, period=provider_period),
        host_key="ths",
        min_interval_env="VIBE_TRADING_THS_MIN_INTERVAL",
        default_interval=1.0,
        headers={"User-Agent": _UA, "Referer": "https://stockpage.10jqka.com.cn/"},
        timeout=20,
    )
    payload = _parse_jsonp(response.text)
    item = payload.get(f"hs_{digits}") if isinstance(payload, dict) else None
    if not isinstance(item, dict) and isinstance(payload, dict):
        nested = payload.get("data")
        if isinstance(nested, dict):
            item = nested.get(f"hs_{digits}") or nested
        else:
            item = payload
    raw_rows = (item or {}).get("data", "")
    if isinstance(raw_rows, list):
        rows = raw_rows
    else:
        rows = str(raw_rows or "").split(";")

    out: list[dict[str, Any]] = []
    for row in rows:
        values = row if isinstance(row, list) else str(row).split(",")
        if len(values) < 6:
            continue
        trade_date = _normalize_ths_bar_time(values[0])
        if not trade_date or trade_date < start_date or trade_date > end_date:
            continue
        out.append({
            "trade_date": trade_date,
            "open": _number(values[1]),
            "high": _number(values[2]),
            "low": _number(values[3]),
            "close": _number(values[4]),
            "volume": _number(values[5]),
            "source": "ths",
        })
    out.sort(key=lambda item: str(item["trade_date"]))
    return out


def _report_publish_date(row: dict[str, Any]) -> date | None:
    for key in ("publishDate", "publish_time", "publishTime", "reportDate", "date"):
        raw = str(row.get(key) or "").strip()
        match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw)
        if not match:
            continue
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
    return None


def eastmoney_reports(code: str, *, limit: int = 20, max_pages: int = 1) -> list[dict[str, Any]]:
    """Fetch recent Eastmoney individual-stock sell-side reports."""
    digits, _ = normalize_a_share_code(code, stock_only=True)
    today = date.today()
    begin = today - timedelta(days=_STOCK_CONTENT_LOOKBACK_DAYS)
    records: list[dict[str, Any]] = []
    for page in range(1, max(1, min(int(max_pages), 5)) + 1):
        response = _em_get(
            _EM_REPORT_URL,
            params={
                "industryCode": "*", "pageSize": "100", "industry": "*",
                "rating": "*", "ratingChange": "*", "beginTime": begin.isoformat(),
                "endTime": today.isoformat(), "pageNo": str(page), "fields": "",
                "qType": "0", "orgCode": "", "code": digits, "rcode": "",
                "p": str(page), "pageNum": str(page), "pageNumber": str(page),
            },
            headers={"Referer": "https://data.eastmoney.com/"},
            timeout=30,
        )
        payload = response.json()
        rows = payload.get("data") or []
        if not rows:
            break
        records.extend(rows)
        if page >= int(payload.get("TotalPage") or 1):
            break
    recent = [
        row for row in records
        if not isinstance(row, dict)
        or (_report_publish_date(row) is None)
        or begin <= _report_publish_date(row) <= today
    ]
    recent.sort(key=lambda row: _report_publish_date(row) or date.min, reverse=True)
    return recent[: max(1, min(int(limit), 50))]


def eastmoney_industry_reports(
    *, days: int = 90, limit: int = 1000, max_pages: int = 10
) -> list[dict[str, Any]]:
    """Fetch recent Eastmoney industry research reports.

    This deliberately uses the industry branch of the shared report endpoint:
    ``qType=1``.  No stock code is sent, so the result cannot silently become
    an individual-stock report query (``qType=0``).
    """
    lookback_days = max(1, min(int(days), 365))
    record_limit = max(1, min(int(limit), 2000))
    page_limit = max(1, min(int(max_pages), 30))
    begin = (datetime.now().date() - timedelta(days=lookback_days)).isoformat()
    records: list[dict[str, Any]] = []
    for page in range(1, page_limit + 1):
        response = _em_get(
            _EM_REPORT_URL,
            params={
                "industryCode": "*", "pageSize": "100", "industry": "*",
                "rating": "*", "ratingChange": "*", "beginTime": begin,
                "endTime": "2030-01-01", "pageNo": str(page), "fields": "",
                "qType": "1",
            },
            headers={"Referer": "https://data.eastmoney.com/"},
            timeout=30,
        )
        payload = response.json()
        rows = payload.get("data") or []
        if not rows:
            break
        records.extend(row for row in rows if isinstance(row, dict))
        if len(records) >= record_limit or page >= int(payload.get("TotalPage") or 1):
            break
    return records[:record_limit]


def eastmoney_hot_industries(*, limit: int = 10) -> dict[str, Any]:
    """Return today's hottest A-share industry boards.

    The score combines live main-fund net inflow, change, and breadth. It is
    intentionally calculated from the live board universe because leadership
    can rotate quickly during the trading day.
    """
    top_n = max(1, min(int(limit), 50))
    ranking_params = {
        "pn": "1", "pz": "100", "po": "1", "np": "1", "fltt": "2", "invt": "2",
        "fid": "f3", "fs": "m:90+t:2", "fields": "f2,f3,f12,f14,f104,f105,f136,f140",
    }
    flow_params = {
        "pn": "1", "pz": "200", "po": "1", "np": "1", "fltt": "2", "invt": "2",
        "fid": "f62", "fs": "m:90+t:2", "fields": "f12,f14,f3,f62,f184,f204,f66,f72,f78,f84",
    }

    def fetch(params: dict[str, str]) -> list[dict[str, Any]]:
        response = _em_get(_EM_BOARD_LIST_URL, params=params, timeout=15)
        data = response.json().get("data") or {}
        diff = data.get("diff") or []
        return list(diff.values()) if isinstance(diff, dict) else [row for row in diff if isinstance(row, dict)]

    try:
        ranking_rows, ranking_status = fetch(ranking_params), "ok"
    except Exception as exc:
        logger.warning("industry board ranking unavailable: %s", exc)
        ranking_rows, ranking_status = [], "unavailable"
    try:
        flow_rows, flow_status = fetch(flow_params), "ok"
    except Exception as exc:
        logger.warning("industry board fund flow unavailable: %s", exc)
        flow_rows, flow_status = [], "unavailable"

    def number(value: Any) -> float | None:
        try:
            return float(value) if value not in (None, "", "-") else None
        except (TypeError, ValueError):
            return None

    merged: dict[str, dict[str, Any]] = {}
    for row in ranking_rows:
        code = str(row.get("f12") or "")
        if code:
            merged[code] = {
                "name": str(row.get("f14") or ""), "board_code": code,
                "change_pct": number(row.get("f3")), "up_count": number(row.get("f104")),
                "down_count": number(row.get("f105")), "leader": row.get("f140") or None,
                "leader_change_pct": number(row.get("f136")),
            }
    for row in flow_rows:
        code = str(row.get("f12") or "")
        if not code:
            continue
        item = merged.setdefault(code, {"name": str(row.get("f14") or ""), "board_code": code})
        item.update({
            "change_pct": item.get("change_pct", number(row.get("f3"))),
            "main_net": number(row.get("f62")), "main_pct": number(row.get("f184")),
            "leader": item.get("leader") or row.get("f204") or None,
            "super_large_net": number(row.get("f66")), "large_net": number(row.get("f72")),
            "medium_net": number(row.get("f78")), "small_net": number(row.get("f84")),
        })

    values = list(merged.values())
    updated_at = datetime.now(timezone.utc).isoformat()
    if not values:
        return {"items": [], "sources": {"industry_ranking": ranking_status, "board_fund_flow": flow_status}, "status": "unavailable", "updated_at": updated_at}

    def normalized(key: str, item: dict[str, Any]) -> float:
        numbers = [float(row[key]) for row in values if row.get(key) is not None]
        value = item.get(key)
        if value is None or not numbers:
            return 0.5
        low, high = min(numbers), max(numbers)
        return 0.5 if high == low else (float(value) - low) / (high - low)

    for item in values:
        total = (item.get("up_count") or 0) + (item.get("down_count") or 0)
        breadth = (item.get("up_count") or 0) / total if total else 0.5
        item["heat_score"] = round(normalized("main_net", item) * 0.55 + normalized("change_pct", item) * 0.30 + breadth * 0.15, 4)
        item["heat_basis"] = "主力净流入55% + 涨跌幅30% + 上涨家数占比15%"
    values.sort(key=lambda row: (row.get("heat_score", 0), row.get("main_net") or 0), reverse=True)
    for rank, item in enumerate(values[:top_n], start=1):
        item["rank"] = rank
    return {"items": values[:top_n], "sources": {"industry_ranking": ranking_status, "board_fund_flow": flow_status}, "status": "ok" if ranking_status == "ok" or flow_status == "ok" else "unavailable", "updated_at": updated_at}


def ths_eps_forecast(code: str) -> list[dict[str, Any]]:
    """Fetch the THS consensus EPS table as JSON-safe records."""
    digits, _ = normalize_a_share_code(code, stock_only=True)
    response = _provider_get(
        f"https://basic.10jqka.com.cn/new/{digits}/worth.html",
        host_key="ths",
        min_interval_env="VIBE_TRADING_THS_MIN_INTERVAL",
        default_interval=1.0,
        headers={"Referer": "https://basic.10jqka.com.cn/"},
        timeout=15,
    )
    response.encoding = "gbk"
    frames = pd.read_html(StringIO(response.text))
    for frame in frames:
        columns = [str(col) for col in frame.columns]
        if any("每股收益" in col or "均值" in col for col in columns):
            return frame.where(pd.notna(frame), None).to_dict(orient="records")
    return frames[0].where(pd.notna(frames[0]), None).to_dict(orient="records") if frames else []


def _news_timestamp(value: Any) -> float:
    """Return a sortable timestamp for Eastmoney news date values."""
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        digits = re.sub(r"[^0-9]", "", text)
        try:
            return float(digits[:14]) if digits else 0.0
        except ValueError:
            return 0.0


def _recent_news(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_STOCK_CONTENT_LOOKBACK_DAYS)).timestamp()
    recent = [
        row for row in rows
        if not isinstance(row, dict)
        or not _news_timestamp(row.get("time") or row.get("published"))
        or _news_timestamp(row.get("time") or row.get("published")) >= cutoff
    ]
    recent.sort(key=lambda row: _news_timestamp(row.get("time") or row.get("published")), reverse=True)
    return recent[: max(1, min(int(limit), 50))]


def _eastmoney_keyword_news(keyword: str, *, limit: int = 20, page: int = 1) -> list[dict[str, Any]]:
    """Fetch one newest-first page of Eastmoney CMS articles for a keyword."""
    query = str(keyword or "").strip()
    if not query:
        return []
    page_size = max(1, min(int(limit), 50))
    page_index = max(1, min(int(page), 100))
    inner = json.dumps({
        "uid": "", "keyword": query, "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                                         "pageIndex": page_index, "pageSize": page_size,
                                         "preTag": "", "postTag": ""}},
    }, separators=(",", ":"), ensure_ascii=False)
    response = _em_get(
        _EM_SEARCH_URL,
        params={"cb": "", "param": inner, "_": "0"},
        headers={"Referer": "https://so.eastmoney.com/"},
        timeout=15,
    )
    payload = _parse_jsonp(response.text)
    articles = ((payload.get("result") or {}).get("cmsArticleWebOld") or []) if isinstance(payload, dict) else []
    clean = re.compile(r"<[^>]+>")
    rows = [{
        "title": clean.sub("", str(item.get("title") or "")),
        "content": clean.sub("", str(item.get("content") or ""))[:280],
        "time": item.get("date", ""),
        "source": item.get("mediaName", ""),
        "url": item.get("url", ""),
    } for item in articles if isinstance(item, dict)]
    rows.sort(key=lambda item: _news_timestamp(item.get("time")), reverse=True)
    return rows[:page_size]


def eastmoney_stock_news(code: str, *, limit: int = 20, page: int = 1) -> list[dict[str, Any]]:
    """Fetch one newest-first page of A-share news with a Sina fallback.

    Eastmoney's search endpoint can return HTTP 200 with only ``passportWeb``
    when its CMS search is unavailable.  Sina's 7x24 feed includes the
    associated stock symbols in ``ext.stocks`` and is therefore a suitable
    per-stock fallback instead of returning an empty news panel.
    """
    digits, _ = normalize_a_share_code(code, stock_only=True)
    page_size = max(1, min(int(limit), 50))
    page_index = max(1, min(int(page), 100))
    rows: list[dict[str, Any]] = []
    try:
        rows = _eastmoney_keyword_news(digits, limit=page_size, page=page_index)
    except Exception as exc:
        logger.warning("Eastmoney stock news unavailable for %s: %s", code, exc)
    if rows:
        return _recent_news(rows, page_size)
    try:
        return _recent_news(sina_stock_news(code, limit=page_size, page=page_index), page_size)
    except Exception as exc:
        logger.warning("Sina stock news fallback unavailable for %s: %s", code, exc)
        return []


def sina_stock_news(code: str, *, limit: int = 20, page: int = 1) -> list[dict[str, Any]]:
    """Fetch Sina 7x24 items explicitly associated with one A-share."""
    digits, market = normalize_a_share_code(code, stock_only=True)
    page_size = max(1, min(int(limit), 50))
    page_index = max(1, min(int(page), 100))
    expected_symbol = f"{market.lower()}{digits}"
    clean = re.compile(r"<[^>]+>")
    rows: list[dict[str, Any]] = []
    # The newest 100 global flashes may contain no mention of a specific
    # security. Scan a few consecutive pages so the detail panel does not
    # incorrectly look empty just because page one was macro-heavy.
    target_count = page_index * page_size
    max_feed_page = min(10, max(5, page_index + 2))
    for feed_page in range(1, max_feed_page + 1):
        response = _provider_get(
            _SINA_STOCK_NEWS_URL,
            host_key="sina",
            min_interval_env=_SINA_MIN_INTERVAL_ENV,
            default_interval=_SINA_DEFAULT_MIN_INTERVAL,
            params={
                "zhibo_id": "152",
                "page_size": "100",
                "page": str(feed_page),
                "dire": "f",
            },
            headers={"Referer": "https://finance.sina.com.cn/"},
            timeout=15,
        )
        feed = (((response.json().get("result") or {}).get("data") or {}).get("feed") or {}).get("list") or []
        for item in feed:
            if not isinstance(item, dict):
                continue
            try:
                ext = json.loads(item.get("ext") or "{}")
            except (TypeError, ValueError):
                ext = {}
            stocks = (ext.get("stocks") or []) if isinstance(ext, dict) else []
            symbols = {
                str(stock.get("symbol") or "").strip().lower()
                for stock in stocks
                if isinstance(stock, dict)
            }
            if expected_symbol not in symbols:
                continue
            text = clean.sub("", str(item.get("rich_text") or "")).strip()
            if not text:
                continue
            rows.append({
                "title": text[:120],
                "content": text[:280],
                "time": item.get("create_time", ""),
                "source": "新浪财经",
                "url": item.get("docurl") or (ext.get("docurl", "") if isinstance(ext, dict) else ""),
            })
        if len(rows) >= target_count:
            break
    rows.sort(key=lambda item: _news_timestamp(item.get("time")), reverse=True)
    start = (page_index - 1) * page_size
    return rows[start:start + page_size]


def eastmoney_stock_boards(code: str, *, limit: int = 100) -> list[dict[str, Any]]:
    """Fetch all industry/concept/region boards associated with an A-share."""
    digits, market = normalize_a_share_code(code, stock_only=True)
    market_code = 1 if market == "SH" else 0
    response = _em_get(
        _EM_BOARD_MEMBERSHIP_URL,
        params={
            "secid": f"{market_code}.{digits}",
            "spt": "3",
            "pi": "0",
            "pz": str(max(1, min(int(limit), 100))),
            "fields": "f12,f13,f14,f3,f2",
            "fltt": "2",
            "po": "1",
        },
        headers={"Referer": "https://quote.eastmoney.com/"},
        timeout=15,
    )
    data = response.json().get("data") or {}
    diff = data.get("diff") or []
    rows = list(diff.values()) if isinstance(diff, dict) else diff
    boards: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("f12") or not row.get("f14"):
            continue
        boards.append({
            "board_code": str(row.get("f12")),
            "board_name": str(row.get("f14")),
            "change_pct": _number(row.get("f3")),
            "price": _number(row.get("f2")),
        })
    return boards[: max(1, min(int(limit), 100))]


def cls_telegraph(*, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch the independent Cailianpress market flash feed."""
    params = {"appName": "CailianpressWeb", "os": "web", "sv": "7.7.5",
              "last_time": "", "refresh_type": "1", "rn": str(max(1, min(int(limit), 50)))}
    query = "&".join(f"{key}={params[key]}" for key in sorted(params))
    sign = hashlib.md5(hashlib.sha1(query.encode()).hexdigest().encode()).hexdigest()
    response = _provider_get(
        _CLS_ROLL_URL,
        host_key="cls",
        min_interval_env="VIBE_TRADING_CLS_MIN_INTERVAL",
        default_interval=0.5,
        params={**params, "sign": sign},
        headers={"Referer": "https://www.cls.cn/"},
        timeout=10,
    )
    rows = ((response.json().get("data") or {}).get("roll_data") or [])
    out: list[dict[str, Any]] = []
    for item in rows:
        ts = item.get("ctime")
        try:
            time = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
        except (TypeError, ValueError, OSError, OverflowError):
            time = ""
        out.append({"title": item.get("title") or item.get("brief", ""),
                    "content": item.get("content") or item.get("brief", ""), "time": time})
    return out[: max(1, min(int(limit), 50))]


def eastmoney_global_news(*, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Eastmoney's 7x24 global fast-news feed."""
    response = _em_get(
        _EM_FAST_NEWS_URL,
        params={"client": "web", "biz": "web_724", "fastColumn": "102",
                "sortEnd": "", "pageSize": str(max(1, min(int(limit), 50))),
                "req_trace": str(uuid.uuid4())},
        headers={"Referer": "https://kuaixun.eastmoney.com/"},
        timeout=10,
    )
    rows = ((response.json().get("data") or {}).get("fastNewsList") or [])
    return [{"title": item.get("title", ""), "summary": str(item.get("summary", ""))[:280],
             "time": item.get("showTime", "")} for item in rows if isinstance(item, dict)][: max(1, min(int(limit), 50))]


def eastmoney_stock_info(code: str) -> dict[str, Any]:
    """Fetch compact profile/valuation fields from Eastmoney push2."""
    digits, market = normalize_a_share_code(code, stock_only=True)
    market_code = 1 if market == "SH" else 0
    response = _em_get(
        _EM_QUOTE_URL,
        params={"fltt": "2", "invt": "2",
                "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43",
                "secid": f"{market_code}.{digits}"},
        timeout=10,
    )
    data = response.json().get("data") or {}
    return {"code": data.get("f57", digits), "name": data.get("f58", ""),
            "industry": data.get("f127", ""), "total_shares": data.get("f84", 0),
            "float_shares": data.get("f85", 0), "mcap": data.get("f116", 0),
            "float_mcap": data.get("f117", 0), "list_date": str(data.get("f189", "")),
            "price": data.get("f43", 0)}


def sina_financial_report(code: str, *, statement: str = "income", limit: int = 8) -> list[dict[str, Any]]:
    """Fetch recent Sina balance/income/cash-flow report periods."""
    digits, market = normalize_a_share_code(code, stock_only=True)
    source = {"balance": "fzb", "income": "lrb", "cashflow": "llb"}.get(statement)
    if source is None:
        raise ValueError("statement must be balance, income, or cashflow")
    response = _provider_get(
        _SINA_FINANCE_URL,
        host_key="sina",
        min_interval_env=_SINA_MIN_INTERVAL_ENV,
        default_interval=_SINA_DEFAULT_MIN_INTERVAL,
        params={"paperCode": _market_prefix(digits, market), "source": source,
                "type": "0", "page": "1", "num": str(max(1, min(int(limit), 12)))},
        timeout=15,
    )
    report_list = (((response.json().get("result") or {}).get("data") or {}).get("report_list") or {})
    rows: list[dict[str, Any]] = []
    for period in sorted(report_list, reverse=True)[: max(1, min(int(limit), 12))]:
        item = report_list[period] or {}
        rec: dict[str, Any] = {"报告期": f"{period[:4]}-{period[4:6]}-{period[6:8]}"}
        for field in item.get("data") or []:
            title = field.get("item_title")
            if not title or field.get("item_value") is None:
                continue
            rec[title] = field.get("item_value")
            if field.get("item_tongbi") not in (None, ""):
                rec[f"{title}_同比"] = field.get("item_tongbi")
        rows.append(rec)
    return rows


def _cninfo_orgid(code: str) -> str:
    global _CNINFO_ORGID_MAP
    if not _CNINFO_ORGID_MAP:
        with _CNINFO_MAP_LOCK:
            if not _CNINFO_ORGID_MAP:
                try:
                    response = _provider_get(
                        _CNINFO_MAP_URL,
                        host_key="cninfo",
                        min_interval_env=_CNINFO_MIN_INTERVAL_ENV,
                        default_interval=_CNINFO_DEFAULT_MIN_INTERVAL,
                        timeout=15,
                    )
                    _CNINFO_ORGID_MAP = {
                        row["code"]: row["orgId"]
                        for row in (response.json().get("stockList") or [])
                        if row.get("code") and row.get("orgId")
                    }
                except Exception as exc:  # fallback below remains useful offline
                    logger.warning("CNINFO issuer map unavailable: %s", exc)
    if code in _CNINFO_ORGID_MAP:
        return _CNINFO_ORGID_MAP[code]
    if code.startswith("6"):
        return f"gssh0{code}"
    if code.startswith(("4", "8", "92")):
        return f"gsbj0{code}"
    return f"gssz0{code}"


def cninfo_announcements(code: str, *, limit: int = 30) -> list[dict[str, Any]]:
    """Fetch listed-company announcements from CNINFO."""
    digits, _ = normalize_a_share_code(code, stock_only=True)
    response = requests.post(
        _CNINFO_ANN_URL,
        data={"stock": f"{digits},{_cninfo_orgid(digits)}", "tabName": "fulltext",
              "pageSize": str(max(1, min(int(limit), 50))), "pageNum": "1", "column": "",
              "category": "", "plate": "", "seDate": "", "searchkey": "",
              "secid": "", "sortName": "", "sortType": "", "isHLtitle": "true"},
        headers={"User-Agent": _UA, "Content-Type": "application/x-www-form-urlencoded",
                 "Referer": "https://www.cninfo.com.cn/new/disclosure",
                 "Origin": "https://www.cninfo.com.cn"},
        timeout=15,
    )
    response.raise_for_status()
    rows: list[dict[str, Any]] = []
    for item in response.json().get("announcements") or []:
        timestamp = item.get("announcementTime")
        if isinstance(timestamp, (int, float)):
            date = datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d")
        else:
            date = str(timestamp or "")[:10]
        rows.append({"title": item.get("announcementTitle", ""),
                     "type": item.get("announcementTypeName", ""), "date": date,
                     "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={item.get('announcementId', '')}"})
    return rows[: max(1, min(int(limit), 50))]


__all__ = [
    "canonical_a_share_code",
    "normalize_a_share_code",
    "tencent_quote",
    "tencent_bars",
    "ths_bars",
    "eastmoney_reports",
    "eastmoney_hot_industries",
    "ths_eps_forecast",
    "eastmoney_stock_news",
    "sina_stock_news",
    "eastmoney_stock_boards",
    "cls_telegraph",
    "eastmoney_global_news",
    "eastmoney_stock_info",
    "sina_financial_report",
    "cninfo_announcements",
]
