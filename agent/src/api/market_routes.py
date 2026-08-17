"""Read-only market overview routes for the frontend dashboard."""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from datetime import datetime, timezone
from typing import Any
from unicodedata import normalize
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from backtest.loaders._http import resolve_min_interval, throttled_get
from backtest.loaders.eastmoney_loader import DataLoader as EastmoneyBarsLoader
from backtest.loaders.yfinance_loader import DataLoader as YFinanceLoader
from src.a_share_data import (
    canonical_a_share_code,
    eastmoney_reports,
    eastmoney_hot_industries,
    eastmoney_industry_reports,
    eastmoney_stock_boards,
    eastmoney_stock_info,
    eastmoney_stock_news,
    sina_financial_report,
    tencent_bars,
    tencent_quote,
    ths_bars,
)
from src.api.security import require_auth
from src.iwencai_skillhub import IwencaiSkillError, search_stock_news as iwencai_stock_news, search_stock_reports as iwencai_stock_reports
from src.market_overview_store import MarketOverviewStore
from src.research.industry_research import get_industry_research_service
from src.session.models import Principal
from src.stock_detail_store import StockDetailStore
from src.tools.symbol_search_tool import SymbolSearchTool
from src.tools.stock_news_tool import StockNewsTool
from src.watchlist_store import WatchlistStore


class WatchlistEntry(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)


class WatchlistsPayload(BaseModel):
    a_share: list[WatchlistEntry] = Field(default_factory=list, max_length=30)
    us: list[WatchlistEntry] = Field(default_factory=list, max_length=30)


A_SHARE_INDICES = (
    ("shanghai", "上证指数", "000001.SH"),
    ("csi300", "沪深300", "000300.SH"),
    ("csi1000", "中证1000", "000852.SH"),
    ("chinext", "创业板指", "399006.SZ"),
)

US_INDICES = (
    ("dow", "道琼斯", "^DJI"),
    ("nasdaq", "纳斯达克", "^IXIC"),
    ("sp500", "标普500", "^GSPC"),
    ("nasdaq100", "纳斯达克100", "^NDX"),
    ("nasdaqGoldenDragon", "纳指金龙中国", "^HXC"),
)

_TENCENT_US_INDEX_CODES = {
    "^DJI": "DJI",
    "^IXIC": "IXIC",
    "^GSPC": "INX",
    "^NDX": "NDX",
    "^HXC": "HXC",
}
_TENCENT_US_URL = "https://qt.gtimg.cn/q="
_TENCENT_HINT_URL = "https://smartbox.gtimg.cn/s3/"
_OVERVIEW_CACHE_TTL_SECONDS = 10.0
_OVERVIEW_REFRESH_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="market-overview-refresh")
_OVERVIEW_REFRESH_LOCK = threading.RLock()
_OVERVIEW_REFRESHING: set[str] = set()
_DETAIL_CACHE_TTL_SECONDS = 24 * 60 * 60
_STOCK_CONTENT_LOOKBACK_DAYS = 365
_DETAIL_REFRESH_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="stock-detail-refresh")
_DETAIL_REFRESH_LOCK = threading.RLock()
_DETAIL_REFRESHING: set[str] = set()
_ROBOT_REPORT_KEYWORDS = (
    ("机器人", ("机器人",)),
    ("减速器", ("减速器", "谐波减速", "rv减速")),
    ("丝杠", ("丝杠", "丝杆", "滚珠螺杆", "滚柱丝杠")),
    ("执行器", ("执行器",)),
    ("灵巧手", ("灵巧手",)),
)


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _snapshot(
    key: str,
    name: str,
    symbol: str,
    *,
    market: str,
    price: float | None,
    change_pct: float | None,
    source: str,
) -> dict[str, Any]:
    change = None
    if price is not None and change_pct is not None:
        change = price * change_pct / (100 + change_pct) if change_pct != -100 else None
    return {
        "key": key,
        "name": name,
        "symbol": symbol,
        "market": market,
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "source": source,
        "status": "ok" if price is not None else "unavailable",
    }


def _unavailable(key: str, name: str, symbol: str, market: str, source: str) -> dict[str, Any]:
    return _snapshot(
        key,
        name,
        symbol,
        market=market,
        price=None,
        change_pct=None,
        source=source,
    )


def _search_tencent_symbols(query: str, market: str) -> list[dict[str, Any]]:
    """Search Chinese names, initials, codes, and US tickers via Tencent."""
    response = throttled_get(
        _TENCENT_HINT_URL,
        host_key="tencent-symbol-search",
        min_interval=resolve_min_interval("VIBE_TRADING_TENCENT_MIN_INTERVAL", 0.15),
        params={"q": query, "t": "all"},
        headers={"Referer": "https://gu.qq.com/"},
    )
    text = response.content.decode("utf-8", errors="replace")
    match = re.search(r'v_hint=(".*")', text)
    if not match:
        return []
    raw = json.loads(match.group(1))
    if raw == "N":
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw.split("^"):
        fields = entry.split("~")
        if len(fields) < 3:
            continue
        venue = fields[0].strip().lower()
        code = fields[1].strip()
        name = fields[2].strip() or code
        if venue in {"sh", "sz", "bj"} and code.isdigit():
            symbol = f"{code.zfill(6)}.{venue.upper()}"
            candidate_market = "a_share"
        elif venue == "us" and code:
            symbol = f"{code.split('.', 1)[0].upper()}.US"
            candidate_market = "us"
        else:
            continue
        if candidate_market != market or symbol in seen:
            continue
        seen.add(symbol)
        results.append({"symbol": symbol, "name": name, "market": market})
    return results[:10]


def _search_market_symbols(query: str, market: str) -> list[dict[str, Any]]:
    """Resolve a user-entered code/name using the repository search tool."""
    try:
        tencent_candidates = _search_tencent_symbols(query, market)
    except Exception:
        tencent_candidates = []
    if tencent_candidates:
        return tencent_candidates

    payload = json.loads(SymbolSearchTool().execute(query=query, limit=15))
    candidates = ((payload.get("data") or {}).get("candidates") or []) if payload.get("ok") else []
    expected_market = "cn" if market == "a_share" else "us"
    normalized = [
        {
            "symbol": str(candidate.get("symbol")),
            "name": str(candidate.get("name") or candidate.get("symbol")),
            "market": market,
        }
        for candidate in candidates
        if candidate.get("market") == expected_market and candidate.get("symbol")
    ][:10]
    if normalized:
        return normalized

    # Keep direct ticker entry useful even when a provider's search endpoint is
    # temporarily unavailable. Names still require the provider search above.
    if market == "a_share" and re.fullmatch(r"(?i)(?:(?:sh|sz|bj)?\d{6}|\d{6}\.(?:sh|sz|bj))", query):
        symbol = canonical_a_share_code(query)
        return [{"symbol": symbol, "name": symbol, "market": market}]
    if market == "us" and re.fullmatch(r"(?i)[a-z][a-z0-9.-]{0,9}(?:\.us)?", query):
        symbol = query.upper() if query.upper().endswith(".US") else f"{query.upper()}.US"
        return [{"symbol": symbol, "name": symbol.removesuffix(".US"), "market": market}]
    return []


def _fetch_yfinance_snapshots(symbols: list[str]) -> dict[str, tuple[float | None, float | None]]:
    """Fetch watchlist quotes in one batch through the project's yfinance loader."""
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=10)
    data = YFinanceLoader().fetch(
        symbols,
        start.isoformat(),
        end.isoformat(),
        interval="1D",
    )
    result: dict[str, tuple[float | None, float | None]] = {}
    for symbol in symbols:
        frame = data.get(symbol)
        if frame is None or frame.empty:
            result[symbol] = (None, None)
            continue
        closes = frame["close"].dropna().tolist()
        if not closes:
            result[symbol] = (None, None)
            continue
        price = _number(closes[-1])
        previous = _number(closes[-2]) if len(closes) > 1 else None
        result[symbol] = (
            (price, None)
            if price is None or previous in (None, 0)
            else (price, (price - previous) / previous * 100)
        )
    return result


def _fetch_tencent_us_snapshots(symbols: list[str]) -> dict[str, tuple[float | None, float | None]]:
    """Fetch a delayed Tencent snapshot when Yahoo/yfinance is unavailable.

    This is deliberately a fallback only. The primary US path remains the
    project's yfinance loader; Tencent keeps the dashboard useful when Yahoo
    returns a transient 403/rate-limit or the local yfinance cookie store is
    unavailable.
    """
    provider_keys = {
        symbol: f"us{_TENCENT_US_INDEX_CODES.get(symbol, symbol.removesuffix('.US'))}"
        for symbol in symbols
    }
    response = throttled_get(
        _TENCENT_US_URL + ",".join(provider_keys.values()),
        host_key="tencent-us",
        min_interval=resolve_min_interval("VIBE_TRADING_TENCENT_MIN_INTERVAL", 0.15),
        headers={"Referer": "https://gu.qq.com/"},
    )
    payloads: dict[str, list[str]] = {}
    text = response.content.decode("gbk", errors="replace")
    for line in text.split(";"):
        if "=" not in line or '"' not in line:
            continue
        provider_key, body = line.split("=", 1)
        key = provider_key.strip().removeprefix("v_")
        payloads[key] = body.split('"', 2)[1].split("~")

    result: dict[str, tuple[float | None, float | None]] = {}
    for symbol, provider_key in provider_keys.items():
        values = payloads.get(provider_key, [])
        if len(values) < 33:
            result[symbol] = (None, None)
            continue
        result[symbol] = (_number(values[3]), _number(values[32]))
    return result


def _fetch_us_snapshots(symbols: list[str]) -> dict[str, tuple[float | None, float | None, str]]:
    """Use yfinance first, then a delayed public snapshot fallback per symbol."""
    try:
        primary = _fetch_yfinance_snapshots(symbols)
    except Exception:
        primary = {}
    missing = [symbol for symbol in symbols if primary.get(symbol, (None, None))[0] is None]
    fallback: dict[str, tuple[float | None, float | None]] = {}
    if missing:
        try:
            fallback = _fetch_tencent_us_snapshots(missing)
        except Exception:
            fallback = {}

    result: dict[str, tuple[float | None, float | None, str]] = {}
    for symbol in symbols:
        price, change_pct = primary.get(symbol, (None, None))
        source = "yfinance"
        if price is None:
            price, change_pct = fallback.get(symbol, (None, None))
            source = "tencent-fallback"
        result[symbol] = (price, change_pct, source)
    return result


def _fetch_a_share_overview() -> dict[str, Any]:
    updated_at = datetime.now(timezone.utc).isoformat()
    try:
        quotes = tencent_quote([symbol for _, _, symbol in A_SHARE_INDICES])
    except Exception:
        quotes = {}
    items: list[dict[str, Any]] = []
    for key, name, symbol in A_SHARE_INDICES:
        quote = quotes.get(symbol) or {}
        items.append(
            _snapshot(
                key,
                name,
                symbol,
                market="a_share",
                price=_number(quote.get("price")),
                change_pct=_number(quote.get("change_pct")),
                source="tencent",
            )
            if quote
            else _unavailable(key, name, symbol, "a_share", "tencent")
        )
    return {"items": items, "updated_at": updated_at}


def _fetch_us_overview() -> dict[str, Any]:
    updated_at = datetime.now(timezone.utc).isoformat()
    try:
        quotes = _fetch_us_snapshots([symbol for _, _, symbol in US_INDICES])
    except Exception:
        quotes = {}
    items: list[dict[str, Any]] = []
    for key, name, symbol in US_INDICES:
        price, change_pct, source = quotes.get(symbol, (None, None, "yfinance"))
        items.append(
            _snapshot(
                key,
                name,
                symbol,
                market="us",
                price=price,
                change_pct=change_pct,
                source=source,
            )
            if price is not None
            else _unavailable(key, name, symbol, "us", source)
        )
    return {"items": items, "updated_at": updated_at}


def _watchlist_items(
    entries: list[dict[str, str]],
    market: str,
    quotes: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in entries:
        symbol = str(entry.get("symbol") or "").upper()
        name = str(entry.get("name") or symbol)
        if market == "a_share":
            quote = quotes.get(symbol) or {}
            items.append(
                _snapshot(
                    symbol,
                    str(quote.get("name") or name),
                    symbol,
                    market=market,
                    price=_number(quote.get("price")),
                    change_pct=_number(quote.get("change_pct")),
                    source="tencent",
                )
                if quote
                else _unavailable(symbol, name, symbol, market, "tencent")
            )
        else:
            price, change_pct, source = quotes.get(symbol, (None, None, "yfinance"))
            items.append(
                _snapshot(symbol, name, symbol, market=market, price=price, change_pct=change_pct, source=source)
                if price is not None
                else _unavailable(symbol, name, symbol, market, source)
            )
    return items


def _fetch_watchlist_overview(profile_scope: str) -> dict[str, Any]:
    watchlists = _get_watchlist_store().load(profile_scope)
    a_symbols = [str(entry["symbol"]).upper() for entry in watchlists.get("a_share", [])]
    us_symbols = [str(entry["symbol"]).upper() for entry in watchlists.get("us", [])]

    def fetch_a_share() -> dict[str, Any]:
        return tencent_quote(a_symbols) if a_symbols else {}

    def fetch_us() -> dict[str, Any]:
        return _fetch_us_snapshots(us_symbols) if us_symbols else {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        a_future = executor.submit(fetch_a_share)
        us_future = executor.submit(fetch_us)
        try:
            a_quotes = a_future.result()
        except Exception:
            a_quotes = {}
        try:
            us_quotes = us_future.result()
        except Exception:
            us_quotes = {}

    return {
        "a_share": _watchlist_items(watchlists.get("a_share", []), "a_share", a_quotes),
        "us": _watchlist_items(watchlists.get("us", []), "us", us_quotes),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _empty_overview_payload(market: str) -> dict[str, Any]:
    definitions = A_SHARE_INDICES if market == "a_share" else US_INDICES
    return {
        "items": [_unavailable(key, name, symbol, market, "database") for key, name, symbol in definitions],
        "updated_at": None,
    }


def _empty_watchlist_overview(profile_scope: str) -> dict[str, Any]:
    try:
        watchlists = _get_watchlist_store().load(profile_scope)
    except Exception:
        watchlists = {"a_share": [], "us": []}
    return {
        "a_share": _watchlist_items(watchlists.get("a_share", []), "a_share", {}),
        "us": _watchlist_items(watchlists.get("us", []), "us", {}),
        "updated_at": None,
    }


def _schedule_overview_refresh(cache_key: str, fetcher: Any) -> bool:
    with _OVERVIEW_REFRESH_LOCK:
        if cache_key in _OVERVIEW_REFRESHING:
            return False
        _OVERVIEW_REFRESHING.add(cache_key)

    def refresh() -> None:
        try:
            payload = fetcher()
            if isinstance(payload, dict):
                MarketOverviewStore().save(cache_key, payload)
        finally:
            with _OVERVIEW_REFRESH_LOCK:
                _OVERVIEW_REFRESHING.discard(cache_key)

    _OVERVIEW_REFRESH_EXECUTOR.submit(refresh)
    return True


def _cached_overview(cache_key: str, fallback: Any, fetcher: Any) -> dict[str, Any]:
    store = MarketOverviewStore()
    cached = store.get(cache_key)
    age = store.age_seconds(cache_key)
    stale = cached is None or age is None or age >= _OVERVIEW_CACHE_TTL_SECONDS
    refreshing = False
    if stale:
        refreshing = _schedule_overview_refresh(cache_key, fetcher)
        with _OVERVIEW_REFRESH_LOCK:
            refreshing = refreshing or cache_key in _OVERVIEW_REFRESHING
    payload = cached if cached is not None else fallback()
    return {
        **payload,
        "cache_status": "refreshing" if refreshing else "cached",
        "from_cache": cached is not None,
    }


def _robot_report_items(records: list[dict[str, Any]], limit: int) -> list[dict[str, str]]:
    """Keep only robot-chain industry reports and normalize their display fields."""
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        title = str(record.get("title") or "").strip()
        industry = str(record.get("industryName") or record.get("indvInduName") or "").strip()
        haystack = f"{title} {industry}".lower()
        segments = [
            label
            for label, keywords in _ROBOT_REPORT_KEYWORDS
            if any(keyword.lower() in haystack for keyword in keywords)
        ]
        if not title or not segments:
            continue
        report_date = str(record.get("publishDate") or record.get("date") or "")[:10]
        institution = str(record.get("orgSName") or record.get("orgName") or "").strip()
        key = (report_date, institution, title)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "date": report_date,
            "institution": institution or "待补",
            "title": title,
            "segment": " / ".join(segments),
        })
    items.sort(key=lambda item: item["date"], reverse=True)
    return items[: max(1, min(int(limit), 200))]


def _get_watchlist_store() -> WatchlistStore:
    """Return the persistent store for the active runtime."""
    return WatchlistStore()


def _get_stock_detail_store() -> StockDetailStore:
    """Return the persistent daily cache for stock-detail data."""
    return StockDetailStore()


def _safe_detail_fetch(
    errors: dict[str, str],
    name: str,
    fetch: Any,
    default: Any,
) -> Any:
    try:
        return fetch()
    except Exception as exc:
        errors[name] = str(exc)
        return default


def _detail_record_age(record: dict[str, Any] | None) -> float | None:
    if not record:
        return None
    try:
        fetched_at = datetime.fromisoformat(str(record.get("fetched_at")))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - fetched_at.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def _schedule_detail_refresh(cache_key: str, fetcher: Any) -> bool:
    with _DETAIL_REFRESH_LOCK:
        if cache_key in _DETAIL_REFRESHING:
            return False
        _DETAIL_REFRESHING.add(cache_key)

    def refresh() -> None:
        try:
            fetcher()
        finally:
            with _DETAIL_REFRESH_LOCK:
                _DETAIL_REFRESHING.discard(cache_key)

    _DETAIL_REFRESH_EXECUTOR.submit(refresh)
    return True


def _detail_cache_status(
    cache_key: str,
    record: dict[str, Any] | None,
    fetcher: Any,
    ttl_seconds: float = _DETAIL_CACHE_TTL_SECONDS,
) -> str:
    age = _detail_record_age(record)
    stale = record is None or age is None or age >= ttl_seconds
    if stale:
        _schedule_detail_refresh(cache_key, fetcher)
    with _DETAIL_REFRESH_LOCK:
        # Keep the first response marked as refreshing even if a very fast
        # background task finished between scheduling and this lock check.
        # Otherwise the frontend can accept the placeholder payload and never
        # poll the newly written cache entry.
        return "refreshing" if stale or cache_key in _DETAIL_REFRESHING else "cached"


def _canonical_us_symbol(symbol: str) -> str:
    raw = str(symbol or "").strip().upper()
    return raw if raw.endswith(".US") else f"{raw}.US"


def _financial_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace(",", "")
    if not text or text in {"-", "--", "N/A"}:
        return None
    try:
        return float(text.rstrip("%"))
    except ValueError:
        return None


def _pick_financial_metric(rows: list[dict[str, Any]], *tokens: str) -> float | None:
    normalized = tuple(token.lower().replace(" ", "") for token in tokens)
    for row in rows:
        for key, value in row.items():
            key_text = str(key).lower().replace(" ", "")
            if all(token in key_text for token in normalized) and not any(
                suffix in key_text for suffix in ("\u540c\u6bd4", "yoy", "\u589e\u957f\u7387")
            ):
                result = _financial_number(value)
                if result is not None:
                    return result
    return None


def _pick_financial_growth(rows: list[dict[str, Any]], *tokens: str) -> float | None:
    normalized = tuple(token.lower().replace(" ", "") for token in tokens)
    for row in rows:
        for key, value in row.items():
            key_text = str(key).lower().replace(" ", "")
            if all(token in key_text for token in normalized) and any(
                suffix in key_text for suffix in ("\u540c\u6bd4", "yoy", "\u589e\u957f\u7387")
            ):
                result = _financial_number(value)
                if result is not None:
                    return result
    return None


def _a_share_financials(code: str) -> dict[str, Any]:
    """Normalize the latest Sina statements into the profile metrics shown in detail."""
    rows: list[dict[str, Any]] = []
    periods: list[str] = []
    for statement in ("income", "balance", "cashflow"):
        for row in sina_financial_report(code, statement=statement, limit=1):
            if not isinstance(row, dict):
                continue
            rows.append(row)
            for key, value in row.items():
                key_text = str(key).lower()
                if any(token in key_text for token in ("period", "date", "\u62a5\u544a")) and value:
                    periods.append(str(value))
    return {
        "period": periods[0] if periods else None,
        "eps": _pick_financial_metric(rows, "\u6bcf\u80a1", "\u6536\u76ca") or _pick_financial_metric(rows, "eps"),
        "bvps": _pick_financial_metric(rows, "\u6bcf\u80a1", "\u51c0\u8d44\u4ea7") or _pick_financial_metric(rows, "bvps"),
        "capital_reserve_ps": _pick_financial_metric(rows, "\u6bcf\u80a1", "\u8d44\u672c\u516c\u79ef"),
        "retained_profit_ps": _pick_financial_metric(rows, "\u6bcf\u80a1", "\u672a\u5206\u914d\u5229\u6da6"),
        "operating_cashflow_ps": _pick_financial_metric(rows, "\u6bcf\u80a1", "\u7ecf\u8425\u73b0\u91d1\u6d41"),
        "revenue": _pick_financial_metric(rows, "\u8425\u4e1a\u603b\u6536\u5165") or _pick_financial_metric(rows, "\u8425\u4e1a\u6536\u5165"),
        "revenue_yoy": _pick_financial_growth(rows, "\u8425\u4e1a\u603b\u6536\u5165") or _pick_financial_growth(rows, "\u8425\u4e1a\u6536\u5165"),
        "net_profit": _pick_financial_metric(rows, "\u51c0\u5229\u6da6"),
        "net_profit_yoy": _pick_financial_growth(rows, "\u51c0\u5229\u6da6"),
        "gross_margin": _pick_financial_metric(rows, "\u6bdb\u5229\u7387"),
        "roe": _pick_financial_metric(rows, "\u51c0\u8d44\u4ea7\u6536\u76ca\u7387") or _pick_financial_metric(rows, "roe"),
    }


_STOCK_PERIODS = {"1d", "1w", "1mo", "1m", "15m", "30m", "60m", "120m"}
_US_EASTERN = ZoneInfo("America/New_York")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _stock_period_dates(period: str) -> tuple[str, str]:
    end = date.today() + timedelta(days=1)
    days = {
        "1d": 365,
        "1w": 365 * 5,
        "1mo": 365 * 10,
        "1m": 6,
        "15m": 365,
        "30m": 365,
        "60m": 365 * 3,
        "120m": 365 * 5,
    }.get(period, 90)
    return (end - timedelta(days=days)).isoformat(), end.isoformat()


def _parallel_stock_fetches(fetchers: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Run independent stock providers together and collect per-section errors."""
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(fetchers)) as executor:
        futures = {name: executor.submit(fetch) for name, fetch in fetchers.items()}
        for name, future in futures.items():
            try:
                values[name] = future.result()
            except Exception as exc:
                values[name] = {} if name not in {"reports", "boards", "bars"} else []
                errors[name] = str(exc)
    return values, errors


def _content_date(value: Any) -> date | None:
    text = str(value or "").strip()
    match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _recent_stock_reports(items: Any) -> list[dict[str, Any]]:
    cutoff = date.today() - timedelta(days=_STOCK_CONTENT_LOOKBACK_DAYS)
    reports = [item for item in (items if isinstance(items, list) else []) if isinstance(item, dict)]
    recent = [
        item for item in reports
        if (published := _content_date(
            item.get("publishDate") or item.get("publish_time") or item.get("publishTime")
            or item.get("reportDate") or item.get("date")
        )) is None or published >= cutoff
    ]
    recent.sort(
        key=lambda item: _content_date(
            item.get("publishDate") or item.get("publish_time") or item.get("publishTime")
            or item.get("reportDate") or item.get("date")
        ) or date.min,
        reverse=True,
    )
    return recent[:20]


def _recent_stock_news(items: Any) -> list[dict[str, Any]]:
    cutoff = date.today() - timedelta(days=_STOCK_CONTENT_LOOKBACK_DAYS)
    news = [item for item in (items if isinstance(items, list) else []) if isinstance(item, dict)]
    recent = [
        item for item in news
        if (published := _content_date(item.get("time") or item.get("published"))) is None
        or published >= cutoff
    ]
    recent.sort(
        key=lambda item: _content_date(item.get("time") or item.get("published")) or date.min,
        reverse=True,
    )
    return recent


def _refresh_stock_info_a_share(canonical: str) -> None:
    store = _get_stock_detail_store()
    static = store.get_static(canonical) or {}
    required = ("quote", "profile", "financials")
    missing = [name for name in required if name not in static]
    if not missing:
        missing = list(required)
    fetchers = {
        "quote": lambda: tencent_quote([canonical]).get(canonical, {}),
        "profile": lambda: eastmoney_stock_info(canonical),
        "financials": lambda: _a_share_financials(canonical),
    }
    values, errors = _parallel_stock_fetches({name: fetchers[name] for name in missing})
    for name, value in values.items():
        if name not in errors:
            store.update_static(canonical, {name: value})


def _refresh_stock_industry_a_share(canonical: str) -> None:
    store = _get_stock_detail_store()
    static = store.get_static(canonical) or {}
    missing = [name for name in ("profile", "boards") if name not in static]
    if not missing:
        missing = ["boards"]
    fetchers = {
        "profile": lambda: eastmoney_stock_info(canonical),
        "boards": lambda: eastmoney_stock_boards(canonical),
    }
    values, errors = _parallel_stock_fetches({name: fetchers[name] for name in missing})
    for name, value in values.items():
        if name not in errors:
            store.update_static(canonical, {name: value})


def _aggregate_stock_bars(bars: list[dict[str, Any]], factor: int) -> list[dict[str, Any]]:
    """Aggregate intraday bars without combining separate trading sessions."""
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
            "high": max(item["high"] for item in bucket),
            "low": min(item["low"] for item in bucket),
            "close": bucket[-1]["close"],
            "volume": sum(item.get("volume") or 0 for item in bucket),
            "source": "ths",
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


def _eastmoney_historical_a_share_bars(canonical: str, start_date: str, end_date: str, period: str) -> list[dict[str, Any]]:
    frame = EastmoneyBarsLoader().fetch([canonical], start_date, end_date, interval=period).get(canonical)
    if frame is None or frame.empty:
        return []
    out: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        stamp = index.to_pydatetime() if hasattr(index, "to_pydatetime") else index
        out.append({
            "trade_date": stamp.strftime("%Y-%m-%d %H:%M") if period.endswith("m") else stamp.strftime("%Y-%m-%d"),
            "open": _number(row.get("open")),
            "high": _number(row.get("high")),
            "low": _number(row.get("low")),
            "close": _number(row.get("close")),
            "volume": _number(row.get("volume")),
            "source": "eastmoney",
        })
    return out


def _refresh_stock_bars_a_share(canonical: str, period: str) -> None:
    start_date, end_date = _stock_period_dates(period)
    if period in {"15m", "30m", "60m"}:
        try:
            bars = ths_bars(canonical, start_date, end_date, period=period)
        except Exception:
            bars = []
        if not bars:
            bars = _eastmoney_historical_a_share_bars(canonical, start_date, end_date, period)
    elif period == "120m":
        try:
            source_bars = ths_bars(canonical, start_date, end_date, period="60m")
        except Exception:
            source_bars = []
        if not source_bars:
            source_bars = _eastmoney_historical_a_share_bars(canonical, start_date, end_date, "60m")
        bars = _aggregate_stock_bars(source_bars, 2)
    else:
        bars = tencent_bars(canonical, start_date, end_date, period=period)
    if bars:
        _get_stock_detail_store().save_bars(canonical, period, bars)


def _refresh_stock_info_us(canonical: str) -> None:
    price, change_pct, source = _fetch_us_snapshots([canonical]).get(canonical, (None, None, "yfinance"))
    _get_stock_detail_store().update_static(canonical, {
        "quote": {"price": price, "change_pct": change_pct, "source": source},
        "profile": {"code": canonical.removesuffix(".US"), "name": canonical.removesuffix(".US")},
        "financials": {},
    })


def _refresh_stock_bars_us(canonical: str, period: str) -> None:
    start, end = _stock_period_dates(period)
    interval = {"1d": "1D", "1w": "1W", "1mo": "1M", "1m": "1m", "15m": "15m", "30m": "30m", "60m": "1H", "120m": "1H"}[period]
    frame = YFinanceLoader().fetch([canonical], start, end, interval=interval).get(canonical)
    bars: list[dict[str, Any]] = []
    if frame is not None and not frame.empty:
        intraday = period in {"1m", "15m", "30m", "60m", "120m"}

        def as_eastern(value: Any) -> datetime:
            stamp = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
            if not isinstance(stamp, datetime):
                stamp = datetime.fromisoformat(str(value))
            return stamp.replace(tzinfo=_US_EASTERN) if stamp.tzinfo is None else stamp.astimezone(_US_EASTERN)

        if intraday:
            session_days = [as_eastern(index).date() for index in frame.index]
            latest_session = max(session_days)
            frame = frame[[as_eastern(index).date() == latest_session for index in frame.index]]
        for index, row in frame.iterrows():
            local_stamp = as_eastern(index).astimezone(_SHANGHAI)
            bars.append({
                "trade_date": local_stamp.strftime("%Y-%m-%d %H:%M") if intraday else local_stamp.strftime("%Y-%m-%d"),
                "open": _number(row.get("open")),
                "high": _number(row.get("high")),
                "low": _number(row.get("low")),
                "close": _number(row.get("close")),
                "volume": _number(row.get("volume")),
            })
    if bars:
        _get_stock_detail_store().save_bars(canonical, period, bars)


def _feed_keys(item: dict[str, Any]) -> list[tuple[str, ...]]:
    title = re.sub(r"\s+", " ", normalize("NFKC", str(item.get("title") or "")).strip()).lower()
    published = str(
        item.get("publishDate") or item.get("publish_time") or item.get("time")
        or item.get("published") or item.get("date") or ""
    )[:10]
    url = str(item.get("url") or "").strip().rstrip("/")
    keys: list[tuple[str, ...]] = []
    if url:
        keys.append(("url", url))
    if title:
        keys.append(("title", title, published))
    return keys


def _merge_feed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge two live feeds, filling missing fields and removing copies."""
    merged: list[dict[str, Any]] = []
    positions: dict[tuple[str, ...], int] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        keys = _feed_keys(item)
        position = next((positions[key] for key in keys if key in positions), None)
        if position is None:
            position = len(merged)
            for key in keys:
                positions[key] = position
            merged.append(item)
            continue
        existing = merged[position]
        for key in keys:
            positions[key] = position
        for field, value in item.items():
            if value not in (None, "", [], {}) and existing.get(field) in (None, "", [], {}):
                existing[field] = value
    return merged


def _fetch_stock_reports(canonical: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch and merge A-share reports from Iwencai and a-stock-data."""
    fetchers = {
        "iwencai": lambda: iwencai_stock_reports(canonical, limit=limit),
        "a_stock_data": lambda: eastmoney_reports(canonical, limit=limit),
    }
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {name: executor.submit(fetch) for name, fetch in fetchers.items()}
        for name, future in futures.items():
            try:
                source_rows = future.result()
            except Exception:
                source_rows = []
            rows.extend(item for item in source_rows if isinstance(item, dict))
    return _merge_feed_rows(rows)[:limit]


def _fetch_stock_news(canonical: str, market: str, page: int, page_size: int) -> list[dict[str, Any]]:
    if market == "a_share":
        def fetch_iwencai() -> list[dict[str, Any]]:
            return iwencai_stock_news(canonical, page=page, page_size=page_size)

        def fetch_a_stock_data() -> list[dict[str, Any]]:
            try:
                return eastmoney_stock_news(canonical, limit=page_size, page=page)
            except TypeError as exc:
                # Keep simple provider fakes and older adapters compatible
                # while the production source supports page-based pagination.
                try:
                    return eastmoney_stock_news(canonical, limit=page_size)
                except TypeError:
                    raise exc

        fetchers = {"iwencai": fetch_iwencai, "a_stock_data": fetch_a_stock_data}
        rows: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {name: executor.submit(fetch) for name, fetch in fetchers.items()}
            for name, future in futures.items():
                try:
                    source_rows = future.result()
                except Exception:
                    source_rows = []
                rows.extend(item for item in source_rows if isinstance(item, dict))
        return _merge_feed_rows(rows)
    raw = json.loads(StockNewsTool().execute(scope="stock", code=canonical, limit=page_size))
    return ((raw.get("data") or {}).get("articles") or []) if raw.get("ok") else []


def _stock_info_a_share(symbol: str) -> dict[str, Any]:
    canonical = canonical_a_share_code(symbol, stock_only=True)
    errors: dict[str, str] = {}
    store = _safe_detail_fetch(errors, "cache", _get_stock_detail_store, None)
    record = _safe_detail_fetch(errors, "cache_read", lambda: store.get_static_with_meta(canonical), None) if store else None
    static = (record or {}).get("payload") or {}
    status = _detail_cache_status(
        f"info:{canonical}",
        record if all(name in static for name in ("quote", "profile", "financials")) else None,
        lambda: _refresh_stock_info_a_share(canonical),
    )
    static = static or {}
    quote = static.get("quote") or {}
    profile = static.get("profile") or {}
    financials = static.get("financials") or {}
    boards = static.get("boards") or []
    merged_profile = {**profile, **quote, "code": canonical, "financials": financials, "boards": boards}
    market_cap = _number(merged_profile.get("mcap"))
    merged_profile["category"] = (
        "Large cap" if market_cap is not None and market_cap >= 100_000_000_000
        else "Mid cap" if market_cap is not None and market_cap >= 20_000_000_000
        else "Small cap" if market_cap is not None else None
    )
    return {
        "symbol": canonical,
        "market": "a_share",
        "profile": merged_profile,
        "financials": financials,
        "errors": errors,
        "cache_status": status,
        "from_cache": record is not None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _stock_reports_a_share(symbol: str) -> dict[str, Any]:
    canonical = canonical_a_share_code(symbol, stock_only=True)
    errors: dict[str, str] = {}
    reports = _safe_detail_fetch(
        errors,
        "reports",
        lambda: _recent_stock_reports(_fetch_stock_reports(canonical, limit=20)),
        [],
    )
    return {
        "symbol": canonical,
        "market": "a_share",
        "reports": reports,
        "errors": errors,
        "cache_status": "live",
        "from_cache": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _stock_industry_a_share(symbol: str) -> dict[str, Any]:
    canonical = canonical_a_share_code(symbol, stock_only=True)
    errors: dict[str, str] = {}
    store = _safe_detail_fetch(errors, "cache", _get_stock_detail_store, None)
    record = _safe_detail_fetch(errors, "cache_read", lambda: store.get_static_with_meta(canonical), None) if store else None
    static = (record or {}).get("payload") or {}
    profile = static.get("profile") or {}
    status = _detail_cache_status(
        f"industry:{canonical}",
        record if all(name in static for name in ("profile", "boards")) else None,
        lambda: _refresh_stock_industry_a_share(canonical),
    )
    static = static or {}
    profile = static.get("profile") or {}
    return {
        "symbol": canonical,
        "market": "a_share",
        "industry": profile.get("industry") or "",
        "boards": static.get("boards") or [],
        "errors": errors,
        "cache_status": status,
        "from_cache": record is not None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _normalise_stock_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose provider bars using the frontend PriceBar contract."""
    return [
        {
            "time": str(item.get("time") or item.get("trade_date") or ""),
            "open": _number(item.get("open")),
            "high": _number(item.get("high")),
            "low": _number(item.get("low")),
            "close": _number(item.get("close")),
            "volume": _number(item.get("volume")),
        }
        for item in bars
        if isinstance(item, dict) and (item.get("time") or item.get("trade_date"))
    ]


def _stock_bars_a_share(symbol: str, period: str = "1d") -> dict[str, Any]:
    canonical = canonical_a_share_code(symbol, stock_only=True)
    errors: dict[str, str] = {}
    store = _safe_detail_fetch(errors, "cache", _get_stock_detail_store, None)
    intraday_periods = {"1m", "15m", "30m", "60m", "120m"}
    record = _safe_detail_fetch(errors, "cache_read", lambda: store.get_bars(canonical, period), None) if store else None
    if period in {"15m", "30m", "60m", "120m"} and record:
        # Invalidate records produced by the old Tencent rolling-minute path;
        # those bars contain only one session and are not historical candles.
        raw_bars = record.get("bars") or []
        if raw_bars and any(item.get("source") == "tencent" for item in raw_bars if isinstance(item, dict)):
            record = None
    ttl = 15.0 if period in intraday_periods else _DETAIL_CACHE_TTL_SECONDS
    status = _detail_cache_status(
        f"bars:{canonical}:{period}",
        record,
        lambda: _refresh_stock_bars_a_share(canonical, period),
        ttl_seconds=ttl,
    )
    bars = (record or {}).get("bars") or []
    return {
        "symbol": canonical,
        "market": "a_share",
        "period": period,
        "bars": _normalise_stock_bars(bars),
        "errors": errors,
        "cache_status": status,
        "from_cache": record is not None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _stock_info_us(symbol: str) -> dict[str, Any]:
    canonical = _canonical_us_symbol(symbol)
    errors: dict[str, str] = {}
    store = _safe_detail_fetch(errors, "cache", _get_stock_detail_store, None)
    record = _safe_detail_fetch(errors, "cache_read", lambda: store.get_static_with_meta(canonical), None) if store else None
    static = (record or {}).get("payload") or {}
    status = _detail_cache_status(
        f"info:{canonical}",
        record if all(name in static for name in ("quote", "profile", "financials")) else None,
        lambda: _refresh_stock_info_us(canonical),
    )
    quote = static.get("quote") or {}
    profile = {**(static.get("profile") or {}), **quote}
    return {
        "symbol": canonical,
        "market": "us",
        "profile": profile,
        "financials": static.get("financials") or {},
        "errors": errors,
        "cache_status": status,
        "from_cache": record is not None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _stock_bars_us(symbol: str, period: str = "1d") -> dict[str, Any]:
    canonical = _canonical_us_symbol(symbol)
    errors: dict[str, str] = {}
    store = _safe_detail_fetch(errors, "cache", _get_stock_detail_store, None)
    intraday_periods = {"1m", "15m", "30m", "60m", "120m"}
    record = _safe_detail_fetch(errors, "cache_read", lambda: store.get_bars(canonical, period), None) if store else None
    status = _detail_cache_status(
        f"bars:{canonical}:{period}",
        record,
        lambda: _refresh_stock_bars_us(canonical, period),
        ttl_seconds=15.0 if period in intraday_periods else _DETAIL_CACHE_TTL_SECONDS,
    )
    return {
        "symbol": canonical,
        "market": "us",
        "period": period,
        "bars": _normalise_stock_bars((record or {}).get("bars") or []),
        "errors": errors,
        "cache_status": status,
        "from_cache": record is not None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _stock_reports_us(symbol: str) -> dict[str, Any]:
    canonical = _canonical_us_symbol(symbol)
    return {
        "symbol": canonical,
        "market": "us",
        "reports": [],
        "errors": {},
        "cache_status": "live",
        "from_cache": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _stock_industry_us(symbol: str) -> dict[str, Any]:
    canonical = _canonical_us_symbol(symbol)
    errors: dict[str, str] = {}
    store = _safe_detail_fetch(errors, "cache", _get_stock_detail_store, None)
    record = _safe_detail_fetch(errors, "cache_read", lambda: store.get_static_with_meta(canonical), None) if store else None
    static = (record or {}).get("payload") or {}
    if "industry" not in static or "boards" not in static:
        if store:
            store.update_static(canonical, {"industry": "", "boards": []})
        static = {**static, "industry": "", "boards": []}
    return {
        "symbol": canonical,
        "market": "us",
        "industry": static.get("industry") or "",
        "boards": static.get("boards") or [],
        "errors": errors,
        "cache_status": "cached",
        "from_cache": record is not None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _stock_news_cached(symbol: str, page: int, page_size: int) -> dict[str, Any]:
    raw = str(symbol or "").strip()
    suffix = raw.rpartition(".")[2].upper() if "." in raw else ""
    market = "a_share" if suffix in {"SH", "SZ", "BJ"} or re.fullmatch(r"\d{6}", raw) else "us"
    canonical = canonical_a_share_code(raw, stock_only=True) if market == "a_share" else _canonical_us_symbol(raw)
    items = _recent_stock_news(_fetch_stock_news(canonical, market, page, page_size))
    return {
        "items": items[:page_size],
        "page": page,
        "page_size": page_size,
        "has_more": len(items) >= page_size,
        "cache_status": "live",
        "from_cache": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _stock_detail_a_share(symbol: str, period: str = "1d", include_news: bool = True) -> dict[str, Any]:
    canonical = canonical_a_share_code(symbol, stock_only=True)
    errors: dict[str, str] = {}
    store = _safe_detail_fetch(errors, "cache", _get_stock_detail_store, None)
    static = _safe_detail_fetch(errors, "cache_read", lambda: store.get_static(canonical), None) if store else None
    if static is None:
        quote = _safe_detail_fetch(errors, "quote", lambda: tencent_quote([canonical]).get(canonical, {}), {})
        profile = _safe_detail_fetch(errors, "profile", lambda: eastmoney_stock_info(canonical), {})
        financials = _safe_detail_fetch(errors, "financials", lambda: _a_share_financials(canonical), {})
        boards = _safe_detail_fetch(errors, "boards", lambda: eastmoney_stock_boards(canonical), [])
        static = {
            "quote": quote,
            "profile": profile,
            "financials": financials,
            "boards": boards,
        }
        if store and not any(key in errors for key in ("quote", "profile", "financials", "boards")):
            _safe_detail_fetch(errors, "cache_write", lambda: store.save_static(canonical, static), None)
    else:
        quote = static.get("quote") or {}
        profile = static.get("profile") or {}
        financials = static.get("financials") or {}
        boards = static.get("boards") or []

    reports = _safe_detail_fetch(errors, "reports", lambda: _recent_stock_reports(_fetch_stock_reports(canonical, limit=20)), [])

    cached_bars = None
    if store and period not in {"1m", "15m", "30m", "60m", "120m"}:
        cached_bars = _safe_detail_fetch(errors, "cache_bars_read", lambda: store.get_bars(canonical, period), None)
    if cached_bars and store and cached_bars.get("refreshed_date") == store.today():
        bars = cached_bars.get("bars") or []
    else:
        fresh_bars = _safe_detail_fetch(
            errors,
            "bars",
            lambda: tencent_bars(canonical, *_stock_period_dates(period), period=period),
            [],
        )
        if fresh_bars:
            bars = fresh_bars
            if store and period not in {"1m", "15m", "30m", "60m", "120m"}:
                _safe_detail_fetch(errors, "cache_bars_write", lambda: store.save_bars(canonical, period, fresh_bars), None)
        else:
            # Keep yesterday's chart usable when the daily refresh provider is
            # temporarily unavailable; the error remains visible to callers.
            bars = (cached_bars or {}).get("bars") or []
    news = _safe_detail_fetch(
        errors,
        "news",
        lambda: _fetch_stock_news(canonical, "a_share", 1, 20),
        [],
    ) if include_news else []
    merged_profile = {**profile, **quote, "code": canonical, "financials": financials, "boards": boards}
    market_cap = _number(merged_profile.get("mcap"))
    merged_profile["category"] = (
        "Large cap" if market_cap is not None and market_cap >= 100_000_000_000
        else "Mid cap" if market_cap is not None and market_cap >= 20_000_000_000
        else "Small cap" if market_cap is not None else None
    )
    return {
        "symbol": canonical,
        "period": period,
        "market": "a_share",
        "profile": merged_profile,
        "financials": financials,
        "bars": [
            {
                "time": str(item.get("trade_date") or ""),
                "open": _number(item.get("open")),
                "high": _number(item.get("high")),
                "low": _number(item.get("low")),
                "close": _number(item.get("close")),
                "volume": _number(item.get("volume")),
            }
            for item in bars
            if isinstance(item, dict) and item.get("trade_date")
        ],
        "reports": reports,
        "news": _recent_stock_news(news),
        "news_pagination": {"page": 1, "page_size": 20, "has_more": len(news) >= 20},
        "errors": errors,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _stock_detail_us(symbol: str, period: str = "1d", include_news: bool = True) -> dict[str, Any]:
    canonical = symbol.upper() if symbol.upper().endswith(".US") else f"{symbol.upper()}.US"
    ticker = canonical.removesuffix(".US")
    errors: dict[str, str] = {}
    snapshot = _safe_detail_fetch(errors, "quote", lambda: _fetch_us_snapshots([canonical]).get(canonical, (None, None, "yfinance")), (None, None, "yfinance"))
    bars: list[dict[str, Any]] = []
    try:
        start, end = _stock_period_dates(period)
        interval = {"1d": "1D", "1w": "1W", "1mo": "1M", "1m": "1m", "15m": "15m", "30m": "30m", "60m": "1H", "120m": "1H"}[period]
        frame = YFinanceLoader().fetch([canonical], start, end, interval=interval).get(canonical)
        if frame is not None and not frame.empty:
            intraday = period in {"1m", "15m", "30m", "60m", "120m"}

            def as_eastern(value: Any) -> datetime:
                stamp = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
                if not isinstance(stamp, datetime):
                    stamp = datetime.fromisoformat(str(value))
                return stamp.replace(tzinfo=_US_EASTERN) if stamp.tzinfo is None else stamp.astimezone(_US_EASTERN)

            # The detail chart is a single-session intraday view. The loader
            # intentionally removes the provider timezone, so resolve the
            # naive Yahoo timestamps as New York time before converting them
            # to Shanghai time for the frontend axis.
            if intraday:
                session_days = [as_eastern(index).date() for index in frame.index]
                latest_session = max(session_days)
                frame = frame[[as_eastern(index).date() == latest_session for index in frame.index]]
            for index, row in frame.iterrows():
                local_stamp = as_eastern(index).astimezone(_SHANGHAI)
                bars.append({
                    "time": local_stamp.strftime("%Y-%m-%d %H:%M") if intraday else index.strftime("%Y-%m-%d"),
                    "open": _number(row.get("open")),
                    "high": _number(row.get("high")),
                    "low": _number(row.get("low")),
                    "close": _number(row.get("close")),
                    "volume": _number(row.get("volume")),
                })
    except Exception as exc:
        errors["bars"] = str(exc)
    raw_news = _safe_detail_fetch(
        errors,
        "news",
        lambda: json.loads(StockNewsTool().execute(scope="stock", code=canonical, limit=20)),
        {"ok": False, "data": {"articles": []}},
    ) if include_news else {"ok": False, "data": {"articles": []}}
    news = _recent_stock_news(((raw_news.get("data") or {}).get("articles") or []) if raw_news.get("ok") else [])
    price, change_pct, source = snapshot
    return {
        "symbol": canonical,
        "period": period,
        "market": "us",
        "profile": {
            "code": ticker,
            "name": ticker,
            "price": price,
            "change_pct": change_pct,
            "source": source,
        },
        "financials": {},
        "bars": bars,
        "reports": [],
        "news": news,
        "news_pagination": {"page": 1, "page_size": 20, "has_more": False},
        "errors": errors,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _stock_detail(symbol: str, period: str = "1d", include_news: bool = True) -> dict[str, Any]:
    if period not in _STOCK_PERIODS:
        raise HTTPException(status_code=400, detail="Unsupported stock bar period")
    raw = str(symbol or "").strip()
    suffix = raw.rpartition(".")[2].upper() if "." in raw else ""
    if suffix in {"SH", "SZ", "BJ"} or re.fullmatch(r"\d{6}", raw):
        return _stock_detail_a_share(raw, period, include_news=include_news)
    if suffix == "US" or re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,9}", raw):
        return _stock_detail_us(raw, period, include_news=include_news)
    raise HTTPException(status_code=400, detail="Unsupported stock symbol")


def _watchlist_scope(principal: Principal) -> str:
    """Use the authenticated principal as the future user-scope boundary."""
    return principal.subject


def register_market_routes(app: FastAPI) -> None:
    @app.get("/market/stocks/{symbol}", dependencies=[Depends(require_auth)])
    def market_stock_detail(
        symbol: str,
        period: str = Query("1d", pattern="^(1d|1w|1mo|1m|15m|30m|60m|120m)$"),
        include_news: bool = Query(True),
    ) -> dict[str, Any]:
        """Return the three-section stock detail payload for the overview page."""
        try:
            return _stock_detail(symbol, period, include_news=include_news)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Stock detail unavailable: {exc}") from exc

    @app.get("/market/stocks/{symbol}/news", dependencies=[Depends(require_auth)])
    def market_stock_news(
        symbol: str,
        page: int = Query(1, ge=1, le=100),
        page_size: int = Query(20, ge=1, le=50),
    ) -> dict[str, Any]:
        """Return one newest-first page fetched directly from the provider."""
        try:
            return _stock_news_cached(symbol, page, page_size)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Stock news unavailable: {exc}") from exc

    @app.get("/market/stocks/{symbol}/info", dependencies=[Depends(require_auth)])
    def market_stock_info(symbol: str) -> dict[str, Any]:
        """Return cached stock information for either A-share or US symbols."""
        try:
            suffix = symbol.rpartition(".")[2].upper() if "." in symbol else ""
            return _stock_info_a_share(symbol) if suffix in {"SH", "SZ", "BJ"} or re.fullmatch(r"\d{6}", symbol) else _stock_info_us(symbol)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Stock info unavailable: {exc}") from exc

    @app.get("/market/stocks/{symbol}/bars", dependencies=[Depends(require_auth)])
    def market_stock_bars(
        symbol: str,
        period: str = Query("1d", pattern="^(1d|1w|1mo|1m|15m|30m|60m|120m)$"),
    ) -> dict[str, Any]:
        """Return one cached stock-bar stream for either market."""
        try:
            suffix = symbol.rpartition(".")[2].upper() if "." in symbol else ""
            return _stock_bars_a_share(symbol, period) if suffix in {"SH", "SZ", "BJ"} or re.fullmatch(r"\d{6}", symbol) else _stock_bars_us(symbol, period)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Stock bars unavailable: {exc}") from exc

    @app.get("/market/stocks/{symbol}/reports", dependencies=[Depends(require_auth)])
    def market_stock_reports(symbol: str) -> dict[str, Any]:
        """Return stock research reports fetched directly from the provider."""
        try:
            suffix = symbol.rpartition(".")[2].upper() if "." in symbol else ""
            return _stock_reports_a_share(symbol) if suffix in {"SH", "SZ", "BJ"} or re.fullmatch(r"\d{6}", symbol) else _stock_reports_us(symbol)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Stock reports unavailable: {exc}") from exc

    @app.get("/market/stocks/{symbol}/industry", dependencies=[Depends(require_auth)])
    def market_stock_industry(symbol: str) -> dict[str, Any]:
        """Return the stock's industry and board memberships independently."""
        try:
            suffix = symbol.rpartition(".")[2].upper() if "." in symbol else ""
            return _stock_industry_a_share(symbol) if suffix in {"SH", "SZ", "BJ"} or re.fullmatch(r"\d{6}", symbol) else _stock_industry_us(symbol)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Stock industry unavailable: {exc}") from exc

    @app.get("/market/watchlists", response_model=WatchlistsPayload)
    def market_watchlists(principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        """Return the persisted overview watchlists."""
        return _get_watchlist_store().load(_watchlist_scope(principal))

    @app.put("/market/watchlists", response_model=WatchlistsPayload)
    def update_market_watchlists(
        payload: WatchlistsPayload,
        principal: Principal = Depends(require_auth),
    ) -> dict[str, Any]:
        """Replace the persisted overview watchlists atomically."""
        return _get_watchlist_store().save(
            _watchlist_scope(principal),
            {
                "a_share": [entry.model_dump() for entry in payload.a_share],
                "us": [entry.model_dump() for entry in payload.us],
            },
        )

    @app.get("/market/search", dependencies=[Depends(require_auth)])
    def market_search(
        query: str = Query(..., min_length=1, max_length=80),
        market: str = Query(..., pattern="^(a_share|us)$"),
    ) -> dict[str, Any]:
        """Search A-share or U.S. candidates for the overview watchlist."""
        try:
            items = _search_market_symbols(query.strip(), market)
        except Exception:
            items = []
        return {"items": items}

    @app.get("/market/overview/a-share", dependencies=[Depends(require_auth)])
    def market_overview_a_share() -> dict[str, Any]:
        """Return the A-share overview cache and refresh it in the background."""
        return _cached_overview("indices:a_share", lambda: _empty_overview_payload("a_share"), _fetch_a_share_overview)

    @app.get("/market/overview/us", dependencies=[Depends(require_auth)])
    def market_overview_us() -> dict[str, Any]:
        """Return the US overview cache and refresh it in the background."""
        return _cached_overview("indices:us", lambda: _empty_overview_payload("us"), _fetch_us_overview)

    @app.get("/market/overview/watchlist", dependencies=[Depends(require_auth)])
    def market_overview_watchlist(principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        """Return cached watchlist quotes and refresh both markets asynchronously."""
        cache_key = f"watchlist:{_watchlist_scope(principal)}"
        return _cached_overview(
            cache_key,
            lambda: _empty_watchlist_overview(_watchlist_scope(principal)),
            lambda: _fetch_watchlist_overview(_watchlist_scope(principal)),
        )

    @app.get("/market/quotes", dependencies=[Depends(require_auth)])
    def market_quotes(
        market: str = Query(..., pattern="^(a_share|us)$"),
        symbols: str = Query(..., min_length=1, max_length=1200),
    ) -> dict[str, Any]:
        """Return current watchlist quotes using the market-specific source."""
        requested = list(dict.fromkeys(item.strip().upper() for item in symbols.split(",") if item.strip()))[:30]
        items: list[dict[str, Any]] = []
        updated_at = datetime.now(timezone.utc).isoformat()
        if market == "a_share":
            try:
                quotes = tencent_quote(requested)
            except Exception:
                quotes = {}
            for symbol in requested:
                quote = quotes.get(symbol) or {}
                items.append(
                    _snapshot(
                        symbol,
                        str(quote.get("name") or symbol),
                        symbol,
                        market=market,
                        price=_number(quote.get("price")),
                        change_pct=_number(quote.get("change_pct")),
                        source="tencent",
                    )
                    if quote
                    else _unavailable(symbol, symbol, symbol, market, "tencent")
                )
        else:
            try:
                us_quotes = _fetch_us_snapshots(requested)
            except Exception:
                us_quotes = {symbol: (None, None, "yfinance") for symbol in requested}
            for symbol in requested:
                price, change_pct, source = us_quotes.get(symbol, (None, None, "yfinance"))
                items.append(_snapshot(symbol, symbol.removesuffix(".US"), symbol, market=market, price=price, change_pct=change_pct, source=source))
        return {"items": items, "updated_at": updated_at}

    @app.get("/market/indices", dependencies=[Depends(require_auth)])
    def market_indices() -> dict[str, Any]:
        """Backward-compatible combined view backed by the two independent caches."""
        a_share = _cached_overview("indices:a_share", lambda: _empty_overview_payload("a_share"), _fetch_a_share_overview)
        us = _cached_overview("indices:us", lambda: _empty_overview_payload("us"), _fetch_us_overview)
        return {
            "items": [*a_share["items"], *us["items"]],
            "updated_at": a_share.get("updated_at") or us.get("updated_at"),
            "cache_status": "refreshing" if "refreshing" in {a_share.get("cache_status"), us.get("cache_status")} else "cached",
            "from_cache": bool(a_share.get("from_cache") and us.get("from_cache")),
        }

    @app.get("/market/research-reports", dependencies=[Depends(require_auth)])
    def market_research_reports(
        days: int = Query(90, ge=1, le=365),
        limit: int = Query(200, ge=1, le=200),
    ) -> dict[str, Any]:
        """Return recent robot-chain industry reports, never individual-stock reports."""
        try:
            records = eastmoney_industry_reports(days=days, limit=1000, max_pages=10)
            items = _robot_report_items(records, limit)
            status = "ok"
        except Exception:
            items = []
            status = "unavailable"
        return {
            "items": items,
            "days": days,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/market/research/industries", dependencies=[Depends(require_auth)])
    def research_industries(
        query: str = Query("", max_length=100),
        limit: int = Query(20, ge=1, le=50),
    ) -> dict[str, Any]:
        return get_industry_research_service().list_industries(query=query, limit=limit)

    @app.get("/market/research/hot-industries", dependencies=[Depends(require_auth)])
    def research_hot_industries(
        limit: int = Query(10, ge=1, le=10),
    ) -> dict[str, Any]:
        result = eastmoney_hot_industries(limit=limit)
        result["as_of_date"] = datetime.now(timezone.utc).date().isoformat()
        result["refresh_policy"] = "intraday; refresh on page load and every 5 minutes"
        return result

    @app.get("/market/research/industries/{industry_id}/reports", dependencies=[Depends(require_auth)])
    def research_industry_reports(
        industry_id: str,
        days: int = Query(90, ge=1, le=730),
        limit: int = Query(50, ge=1, le=200),
        section_id: str | None = Query(None, max_length=100),
    ) -> dict[str, Any]:
        return get_industry_research_service().reports(industry_id, days=days, limit=limit, section_id=section_id)

    @app.get("/market/research/industries/{industry_id}", dependencies=[Depends(require_auth)])
    def research_industry(industry_id: str) -> dict[str, Any]:
        return get_industry_research_service().detail(industry_id)

    @app.post("/market/research/industries/{industry_id}/analysis", dependencies=[Depends(require_auth)])
    def start_research_analysis(
        industry_id: str,
        force: bool = Query(False),
    ) -> dict[str, Any]:
        return get_industry_research_service().start_analysis(industry_id, force=force)

    @app.get("/market/research/analysis/{job_id}", dependencies=[Depends(require_auth)])
    def research_analysis_job(job_id: str) -> dict[str, Any]:
        return get_industry_research_service().store.get_job(job_id) or {
            "job_id": job_id,
            "status": "unavailable",
            "error": "analysis job not found",
        }
