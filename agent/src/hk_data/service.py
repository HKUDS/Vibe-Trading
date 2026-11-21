"""Current HK quotes with explicit source time, delay and freshness.

Public endpoints are best-effort research feeds.  A recent retrieval never
changes the provider timestamp or proves real-time exchange entitlement.
"""

from __future__ import annotations

import json
import math
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from backtest.engines._market_hooks import hk_counter_currency
from backtest.loaders._http import (
    resolve_min_interval,
    throttled_get,
    throttled_get_json,
)

UTC = timezone.utc
HKT = ZoneInfo("Asia/Hong_Kong")
MAX_SYMBOLS = 100
SOURCES = ("auto", "yahoo", "tencent", "futu")
DEFAULT_SYMBOLS = ["00700.HK", "00005.HK", "01299.HK", "00941.HK", "00388.HK"]
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="


def normalize_symbol(value: str) -> str:
    """Accept 700, 0700.HK, 00700.HK or HK.00700; preserve currency counters."""
    if not isinstance(value, str):
        raise ValueError("Each symbol must be a string")
    value = value.strip().upper()
    if value.startswith("HK."):
        value = value[3:]
    elif value.endswith(".HK"):
        value = value[:-3]
    if not re.fullmatch(r"[0-9]{1,5}", value) or int(value) == 0:
        raise ValueError("Use numeric Hong Kong symbols such as 0700.HK")
    return f"{int(value):05d}.HK"


def normalize_symbols(values: list[str]) -> list[str]:
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_SYMBOLS:
        raise ValueError(f"Provide 1 to {MAX_SYMBOLS} Hong Kong symbols")
    return list(dict.fromkeys(normalize_symbol(value) for value in values))


def iso_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds")


def _number(value: Any, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean quote field")
    number = float(value)
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        raise ValueError("Invalid quote field")
    return number


def quote_age(quote: dict, now: datetime, max_age_seconds: float) -> dict:
    """Recompute freshness without replacing the original observation time."""
    if (
        isinstance(max_age_seconds, bool)
        or not isinstance(max_age_seconds, (int, float))
        or not math.isfinite(max_age_seconds)
        or max_age_seconds <= 0
    ):
        raise ValueError("max_age_seconds must be a finite positive number")
    result = dict(quote)
    provider_time = datetime.fromisoformat(result["provider_time"])
    if provider_time.tzinfo is None:
        raise ValueError("Provider timestamp must include a timezone")
    age = (now.astimezone(UTC) - provider_time.astimezone(UTC)).total_seconds()
    if age < -5:
        raise ValueError("Provider timestamp is in the future")
    result["age_seconds"] = round(max(0.0, age), 3)
    result["status"] = "fresh" if age <= max_age_seconds else "stale"
    return result


def _quote(
    symbol,
    source,
    price,
    provider_time,
    now,
    *,
    currency,
    volume=None,
    delay=None,
    session_state="unknown",
) -> dict:
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Provider did not declare a usable currency")
    return {
        "symbol": symbol,
        "source": source,
        "price": _number(price, positive=True),
        "currency": currency,
        "provider_time": iso_time(provider_time),
        "observed_at_utc": iso_time(now),
        "adjustment": "raw",
        "volume": None if volume is None else _number(volume),
        "volume_unit": None if volume is None else "shares",
        "volume_scope": "session_cumulative" if volume is not None else None,
        "declared_delay_seconds": delay,
        "delay_status": "delayed" if delay else "unknown",
        "session_state": session_state,
    }


def _yahoo(symbol: str, now: datetime) -> dict:
    yahoo_symbol = f"{int(symbol[:-3]):04d}.HK"
    payload = throttled_get_json(
        YAHOO_CHART_URL + yahoo_symbol,
        host_key="yahoo",
        min_interval=resolve_min_interval("VIBE_TRADING_YAHOO_MIN_INTERVAL", 0.6),
        params={"interval": "1m", "range": "1d"},
        timeout=8.0,
    )
    now = datetime.now(UTC)
    chart = payload["chart"]
    if chart.get("error"):
        raise ValueError("Yahoo rejected the symbol")
    meta = chart["result"][0]["meta"]
    if normalize_symbol(meta["symbol"]) != symbol:
        raise ValueError("Yahoo returned a different symbol")
    # Both fields belong to the same snapshot. Do not pair this price with
    # the final chart-bar timestamp, which can have different semantics.
    stamp = _number(meta["regularMarketTime"], positive=True)
    provider_time = datetime.fromtimestamp(stamp, UTC)
    session = "unknown"
    period = meta.get("currentTradingPeriod", {}).get("regular", {})
    start, end = period.get("start"), period.get("end")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)):
        session = (
            "regular_window"
            if start <= now.timestamp() <= end
            else "outside_regular_window"
        )
    return _quote(
        symbol,
        "yahoo",
        meta["regularMarketPrice"],
        provider_time,
        now,
        currency=meta["currency"],
        volume=meta.get("regularMarketVolume"),
        delay=900,
        session_state=session,
    )


def _tencent(symbols: list[str], now: datetime) -> tuple[list[dict], list[dict]]:
    response = throttled_get(
        TENCENT_QUOTE_URL + ",".join("r_hk" + symbol[:-3] for symbol in symbols),
        host_key="tencent",
        min_interval=resolve_min_interval("VIBE_TRADING_TENCENT_MIN_INTERVAL", 0.6),
        timeout=8.0,
    )
    response.raise_for_status()
    now = datetime.now(UTC)
    response.encoding = "gbk"
    matches = dict(re.findall(r'v_(?:r_)?hk([0-9]{5})="([^"\r\n]*)"', response.text))
    quotes, errors = [], []
    for symbol in symbols:
        try:
            parts = matches[symbol[:-3]].split("~")
            if parts[2].zfill(5) != symbol[:-3]:
                raise ValueError("Tencent returned a different symbol")
            # Tencent's HK quote timestamp is YYYY/MM/DD HH:MM:SS. Older
            # responses used compact digits; both are strictly parsed in HKT.
            raw_time = parts[30]
            provider_time = None
            for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S"):
                try:
                    provider_time = datetime.strptime(raw_time, fmt).replace(tzinfo=HKT)
                    break
                except ValueError:
                    continue
            if provider_time is None:
                raise ValueError("Missing Tencent quote time")
            # Currency follows the repository's shared HKEX counter allocation.
            # Keep the observed cumulative quantity; its unit has not yet been
            # reconciled to an exchange record at an identical timestamp.
            quote = _quote(
                symbol,
                "tencent",
                parts[3],
                provider_time,
                now,
                currency=hk_counter_currency(symbol),
                volume=parts[6] or None,
            )
            quote["change_pct"] = (
                float(parts[32]) if len(parts) > 32 and parts[32] else None
            )
            if quote["change_pct"] is not None and not math.isfinite(
                quote["change_pct"]
            ):
                raise ValueError("Invalid percentage change")
            quote["endpoint"] = "r_hk"
            quote["volume_unit"] = None
            quotes.append(quote)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            errors.append(_failure("tencent", symbol, exc))
    return quotes, errors


def _futu(symbols: list[str], now: datetime) -> tuple[list[dict], list[dict]]:
    # The SDK can wait indefinitely for OpenD. Keep it in a bounded worker so
    # a stalled local bridge cannot wedge the agent or continuous collector.
    with socket.create_connection(("127.0.0.1", 11111), timeout=1.0):
        pass
    completed = subprocess.run(
        [sys.executable, "-m", "src.hk_data.futu_worker"],
        input=json.dumps(symbols),
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    payload = json.loads(completed.stdout)
    now = datetime.now(UTC)
    quotes, errors = [], []
    by_code = {str(row["code"]): row for row in payload["rows"]}
    for symbol in symbols:
        try:
            row = by_code["HK." + symbol[:-3]]
            provider_time = datetime.strptime(
                str(row["update_time"]), "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=HKT)
            quotes.append(
                _quote(
                    symbol,
                    "futu",
                    row["last_price"],
                    provider_time,
                    now,
                    currency=hk_counter_currency(symbol),
                    volume=row.get("volume"),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            errors.append(_failure("futu", symbol, exc))
    return quotes, errors


def _failure(source: str, symbol: str, exc: Exception) -> dict:
    # Do not expose raw HTTP response bodies, Futu login errors or local paths.
    return {
        "source": source,
        "symbol": symbol,
        "error": type(exc).__name__,
        "message": "Quote unavailable or invalid; check provider availability and symbol.",
    }


def fetch_quotes(
    symbols: list[str], source: str = "auto", max_age_seconds: float = 1200
) -> dict:
    """Fetch quotes once; auto uses Yahoo, then Tencent for missing/stale names.

    Explicit sources never fall back.  Unknown-delay sources remain labelled
    unknown even when their provider timestamp is recent. No API keys required
    for Yahoo/Tencent; Futu is opt-in and requires installed local OpenD.
    """
    symbols = normalize_symbols(symbols)
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    if (
        isinstance(max_age_seconds, bool)
        or not isinstance(max_age_seconds, (int, float))
        or not math.isfinite(max_age_seconds)
        or max_age_seconds <= 0
    ):
        raise ValueError("max_age_seconds must be a finite positive number")
    quotes: dict[str, dict] = {}
    errors = []
    if source in ("auto", "yahoo"):
        consecutive_http_errors = 0
        for symbol in symbols:
            if consecutive_http_errors >= 3:
                errors.append(
                    {
                        "source": "yahoo",
                        "symbol": symbol,
                        "error": "ProviderUnavailable",
                        "message": "Skipped after three consecutive HTTP failures; retry on the next poll.",
                    }
                )
                continue
            try:
                now = datetime.now(UTC)
                candidate = _yahoo(symbol, now)
                quotes[symbol] = quote_age(
                    candidate, datetime.now(UTC), max_age_seconds
                )
                consecutive_http_errors = 0
            except Exception as exc:
                errors.append(_failure("yahoo", symbol, exc))
                consecutive_http_errors = (
                    consecutive_http_errors + 1
                    if isinstance(exc, requests.RequestException)
                    else 0
                )
    pending = [
        symbol
        for symbol in symbols
        if symbol not in quotes or quotes[symbol]["status"] == "stale"
    ]
    next_source = "tencent" if source == "auto" and pending else source
    if next_source in ("tencent", "futu"):
        wanted = pending if source == "auto" else symbols
        try:
            now = datetime.now(UTC)
            candidates, failures = (_tencent if next_source == "tencent" else _futu)(
                wanted, now
            )
            errors.extend(failures)
            for candidate in candidates:
                try:
                    candidate = quote_age(candidate, datetime.now(UTC), max_age_seconds)
                    previous = quotes.get(candidate["symbol"])
                    if (
                        previous is None
                        or candidate["provider_time"] > previous["provider_time"]
                    ):
                        quotes[candidate["symbol"]] = candidate
                except (ValueError, TypeError) as exc:
                    errors.append(_failure(next_source, candidate["symbol"], exc))
        except Exception as exc:
            errors.extend(_failure(next_source, symbol, exc) for symbol in wanted)
    now = datetime.now(UTC)
    rows = [
        quote_age(quotes[symbol], now, max_age_seconds)
        for symbol in symbols
        if symbol in quotes
    ]
    missing = [symbol for symbol in symbols if symbol not in quotes]
    return {
        "ok": bool(rows),
        "status": "error" if not rows else "partial" if missing else "ok",
        "market": "HK",
        "source": source,
        "observed_at_utc": iso_time(now),
        "quotes": rows,
        "missing": missing,
        "errors": errors,
        "note": "Freshness measures provider timestamp age; it does not verify exchange real-time rights. Yahoo HK quotes are 15 minutes delayed.",
    }
