"""
ccxt-based fetchers for data not exposed by OKX public endpoints.

Use cases:
- Funding rate history (Binance / Bybit support multi-year via ccxt; longer than OKX public endpoint)
- OI history (Bybit / Binance publish historical OI publicly via ccxt)
- Long/short ratio (some exchanges)
"""

from datetime import datetime, timedelta, timezone
import time

import ccxt
import pandas as pd


def fetch_funding_rate_history_ccxt(
    exchange_name: str = "binance",
    symbol: str = "BTC/USDT:USDT",
    days: int = 730,
    since_dt: datetime | None = None,
    until_dt: datetime | None = None,
) -> pd.DataFrame:
    """Fetch funding rate history via ccxt (Binance/Bybit support multi-year).

    Args:
        exchange_name: 'binance', 'bybit', 'okx', etc.
        symbol: ccxt unified perp symbol (e.g. 'BTC/USDT:USDT')
        days: lookback window (used only if since_dt/until_dt not set)
        since_dt: optional explicit start (tz-aware UTC). Overrides days.
        until_dt: optional explicit end (tz-aware UTC). Defaults to now.

    Returns:
        DataFrame indexed by UTC time (tz-aware), column 'funding_rate' (float).
    """
    if exchange_name == "binance":
        exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
        page_limit = 1000
    elif exchange_name == "bybit":
        exchange = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})
        page_limit = 200
    else:
        exchange = getattr(ccxt, exchange_name)({"enableRateLimit": True})
        page_limit = 100

    if since_dt is not None:
        since = int(since_dt.timestamp() * 1000)
    else:
        since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    if until_dt is not None:
        end_ms = int(until_dt.timestamp() * 1000)
    else:
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    rows: list = []
    while since < end_ms:
        try:
            batch = exchange.fetch_funding_rate_history(symbol, since=since, limit=page_limit)
        except Exception as e:
            print(f"  fetch_funding_rate_history error at since={since}: {e}")
            break
        if not batch:
            break
        for entry in batch:
            ts = entry.get("timestamp")
            rate = entry.get("fundingRate")
            if ts is None or rate is None:
                continue
            if ts > end_ms:
                continue
            rows.append(
                {
                    "time": datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                    "funding_rate": float(rate),
                }
            )
        last_ts = batch[-1].get("timestamp")
        if last_ts is None or last_ts <= since:
            break
        since = last_ts + 1
        time.sleep(0.1)

    if not rows:
        return pd.DataFrame(columns=["funding_rate"])
    df = pd.DataFrame(rows).drop_duplicates("time").set_index("time").sort_index()
    return df


def fetch_oi_history_bybit(symbol: str = "BTC/USDT:USDT", days: int = 90, timeframe: str = "1h") -> pd.DataFrame:
    """Fetch hourly historical open interest from Bybit via ccxt.

    Args:
        symbol: ccxt unified symbol for Bybit perpetual (e.g. "BTC/USDT:USDT")
        days: lookback
        timeframe: "5m" / "15m" / "30m" / "1h" / "4h" / "1d"

    Returns:
        DataFrame indexed by UTC time, columns: oi (contracts), oi_usd
    """
    exchange = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

    rows: list[dict] = []
    # ccxt's fetch_open_interest_history paginates by since + limit
    while True:
        data = exchange.fetch_open_interest_history(symbol, timeframe=timeframe, since=since, limit=200)
        if not data:
            break
        for d in data:
            rows.append(
                {
                    "time": datetime.fromtimestamp(d["timestamp"] / 1000, tz=timezone.utc),
                    "oi": float(d.get("openInterestAmount") or d.get("openInterestValue") or 0),
                    "oi_usd": float(d.get("openInterestValue") or 0),
                }
            )
        last_ts = data[-1]["timestamp"]
        if last_ts <= since:
            break
        since = last_ts + 1
        if datetime.fromtimestamp(since / 1000, tz=timezone.utc) >= datetime.now(timezone.utc):
            break

    if not rows:
        return pd.DataFrame(columns=["oi", "oi_usd"])
    df = pd.DataFrame(rows).drop_duplicates("time").set_index("time").sort_index()
    return df


def fetch_ohlcv_ccxt(exchange_name: str, symbol: str, days: int, timeframe: str = "1h") -> pd.DataFrame:
    """Generic OHLCV fetcher via ccxt (fallback for exchanges other than OKX)."""
    exchange = getattr(ccxt, exchange_name)({"enableRateLimit": True})
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    rows: list[dict] = []
    while True:
        data = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not data:
            break
        for ts, o, h, l, c, v in data:
            rows.append(
                {
                    "time": datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                }
            )
        last_ts = data[-1][0]
        if last_ts <= since:
            break
        since = last_ts + 1
        if datetime.fromtimestamp(since / 1000, tz=timezone.utc) >= datetime.now(timezone.utc):
            break
    df = pd.DataFrame(rows).drop_duplicates("time").set_index("time").sort_index()
    return df
