"""
CoinGecko public fetchers (free, no auth).

Sources:
- /coins/<coin_id>/market_chart: daily market cap timeseries for the top
  USD-pegged stablecoins (USDT, USDC, DAI). Used as a proxy for aggregate
  stablecoin supply — when supply expands, fresh capital is entering crypto;
  when it contracts, capital is leaving.

Rate-limit note: the public CoinGecko API allows ~30 calls/min. This module
caches per-process to avoid hammering the endpoint on repeated lookups.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

import pandas as pd
import requests

BASE_URL = "https://api.coingecko.com/api/v3"

STABLECOIN_IDS: tuple[str, ...] = ("tether", "usd-coin", "dai")


def _fetch_market_caps(coin_id: str, days: int) -> pd.Series:
    """Fetch daily market-cap timeseries for one CoinGecko coin id.

    Args:
        coin_id: CoinGecko id, e.g. "tether", "usd-coin", "dai".
        days:    Lookback window in days (CoinGecko caps free tier at 365
                 per call without an API key — caller is responsible for
                 chunking longer ranges if needed).

    Returns:
        pd.Series indexed by UTC timestamp (daily 00:00 UTC) with float
        market-cap values in USD.
    """
    r = requests.get(
        f"{BASE_URL}/coins/{coin_id}/market_chart",
        params={"vs_currency": "usd", "days": str(days), "interval": "daily"},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    market_caps = payload.get("market_caps") or []

    rows: list[dict] = []
    for ts_ms, cap in market_caps:
        rows.append(
            {
                "time": datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc),
                "market_cap": float(cap),
            }
        )
    if not rows:
        return pd.Series(name="market_cap", dtype="float64")
    df = pd.DataFrame(rows).drop_duplicates("time").set_index("time").sort_index()
    return df["market_cap"]


@lru_cache(maxsize=4)
def _fetch_market_caps_cached(coin_id: str, days: int) -> pd.Series:
    """Process-local cache wrapper around _fetch_market_caps."""
    return _fetch_market_caps(coin_id, days)


def fetch_stablecoin_supply(
    symbol: str | None = None,
    days: int = 365,
    coin_ids: tuple[str, ...] = STABLECOIN_IDS,
) -> pd.DataFrame:
    """Fetch aggregate stablecoin market cap (USDT + USDC + DAI by default).

    The ``symbol`` arg is accepted for SOURCE_REGISTRY signature symmetry but
    ignored — stablecoin supply is a market-wide series, not symbol-specific.

    Args:
        symbol:   Ignored (kept for fetcher signature compatibility).
        days:     Lookback in days. CoinGecko free tier returns daily granularity
                  for ranges > 90d; the caller forward-fills onto hourly index.
        coin_ids: CoinGecko coin ids whose market caps are summed.

    Returns:
        DataFrame indexed by UTC daily timestamp, columns:
          - stablecoin_supply: sum of market caps across coin_ids (USD float).
    """
    series_per_coin: list[pd.Series] = []
    for coin_id in coin_ids:
        try:
            s = _fetch_market_caps_cached(coin_id, days)
        except requests.RequestException as exc:
            print(f"[coingecko] {coin_id}: fetch failed ({exc}); skipping")
            continue
        if s.empty:
            continue
        series_per_coin.append(s.rename(coin_id))

    if not series_per_coin:
        return pd.DataFrame(columns=["stablecoin_supply"])

    aligned = pd.concat(series_per_coin, axis=1).sort_index()
    aligned = aligned.ffill()
    total = aligned.sum(axis=1, min_count=1)
    return total.rename("stablecoin_supply").to_frame()
