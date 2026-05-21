"""
OKX V5 public REST API fetchers. No auth required.

Endpoints:
- /public/funding-rate-history: 8h funding settlements (paginated)
- /market/candles: recent OHLCV (~1440 bars deep)
- /market/history-candles: historical OHLCV (longer history)
- /public/open-interest: current OI snapshot only (historical OI requires auth)
"""

from datetime import datetime, timedelta, timezone
import time

import pandas as pd
import requests

BASE_URL = "https://www.okx.com/api/v5"
DEFAULT_PAGE_SLEEP = 0.15


def _parse_ms(ts_str: str) -> datetime:
    """OKX timestamps are millisecond-epoch strings."""
    return datetime.fromtimestamp(int(ts_str) / 1000, tz=timezone.utc)


def fetch_funding_history(symbol: str, days: int) -> pd.DataFrame:
    """Fetch funding rate history for a perpetual swap.

    Args:
        symbol: e.g. "BTC-USDT-SWAP"
        days: lookback window in days

    Returns:
        DataFrame indexed by UTC time, column ``funding_rate`` (float).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows: list[dict] = []
    after_ms: int | None = None
    while True:
        params = {"instId": symbol, "limit": 100}
        if after_ms:
            params["after"] = str(after_ms)
        r = requests.get(f"{BASE_URL}/public/funding-rate-history", params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "0":
            raise RuntimeError(f"funding-rate-history error: {data}")
        items = data.get("data", [])
        if not items:
            break
        for it in items:
            rows.append(
                {
                    "time": _parse_ms(it["fundingTime"]),
                    "funding_rate": float(it["fundingRate"]),
                }
            )
        earliest = _parse_ms(items[-1]["fundingTime"])
        if earliest < cutoff:
            break
        after_ms = int(earliest.timestamp() * 1000)
        time.sleep(DEFAULT_PAGE_SLEEP)
    df = pd.DataFrame(rows).drop_duplicates("time").set_index("time").sort_index()
    return df[df.index >= cutoff]


def fetch_candles(
    symbol: str,
    days: int,
    bar: str = "1H",
    use_history_endpoint: bool = True,
) -> pd.DataFrame:
    """Fetch OHLCV candles for a perpetual swap.

    Args:
        symbol: e.g. "BTC-USDT-SWAP"
        days: lookback window
        bar: OKX bar size (e.g. "1H", "4H", "1D")
        use_history_endpoint: True -> /market/history-candles (deep), False -> /market/candles (~1440 bars)

    Returns:
        DataFrame indexed by UTC time, columns: open/high/low/close/volume.
    """
    endpoint = "history-candles" if use_history_endpoint else "candles"
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows: list[dict] = []
    after_ms: int | None = None
    while True:
        params = {"instId": symbol, "bar": bar, "limit": 100}
        if after_ms:
            params["after"] = str(after_ms)
        r = requests.get(f"{BASE_URL}/market/{endpoint}", params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "0":
            raise RuntimeError(f"{endpoint} error: {data}")
        items = data.get("data", [])
        if not items:
            break
        for it in items:
            rows.append(
                {
                    "time": _parse_ms(it[0]),
                    "open": float(it[1]),
                    "high": float(it[2]),
                    "low": float(it[3]),
                    "close": float(it[4]),
                    "volume": float(it[5]),
                }
            )
        earliest = _parse_ms(items[-1][0])
        if earliest < cutoff:
            break
        after_ms = int(earliest.timestamp() * 1000)
        time.sleep(DEFAULT_PAGE_SLEEP)
    df = pd.DataFrame(rows).drop_duplicates("time").set_index("time").sort_index()
    return df[df.index >= cutoff]


def fetch_current_oi(symbol: str) -> dict:
    """Fetch current OI snapshot. Historical OI requires authenticated endpoint."""
    r = requests.get(
        f"{BASE_URL}/public/open-interest",
        params={"instType": "SWAP", "instId": symbol},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") == "0" and data.get("data"):
        return data["data"][0]
    return {}
