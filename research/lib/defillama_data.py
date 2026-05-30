"""
DefiLlama public fetchers (free, no auth, multi-year history).

Source:
- https://stablecoins.llama.fi/stablecoincharts/all : daily aggregate
  circulating supply (USD) across ALL tracked stablecoins, back to 2017.
  Used as a proxy for aggregate stablecoin supply — when supply expands,
  fresh capital is entering crypto; when it contracts, capital is leaving.

Why DefiLlama over CoinGecko: CoinGecko's free tier caps the market-chart
endpoint at 365 days per call, which limited the stablecoin factor to ~1 year
and made out-of-sample testing impossible. DefiLlama returns the full multi-year
daily history in a single unauthenticated call, and aggregates every tracked
USD-pegged stablecoin (not just USDT/USDC/DAI).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import pandas as pd
import requests

BASE_URL = "https://stablecoins.llama.fi"

#: Endpoint returning the full daily aggregate stablecoin chart.
_CHART_PATH = "/stablecoincharts/all"


@lru_cache(maxsize=2)
def _fetch_chart_cached() -> pd.Series:
    """Fetch the full daily peggedUSD circulating-supply series (process-cached).

    Returns:
        pd.Series indexed by UTC daily timestamp with float USD values, covering
        the entire available history (no date filtering).
    """
    r = requests.get(f"{BASE_URL}{_CHART_PATH}", timeout=30)
    r.raise_for_status()
    payload = r.json()

    rows: list[dict] = []
    for entry in payload or []:
        ts = entry.get("date")
        circ = entry.get("totalCirculatingUSD") or {}
        val = circ.get("peggedUSD")
        if ts is None or val is None:
            continue
        rows.append(
            {
                "time": datetime.fromtimestamp(int(ts), tz=timezone.utc),
                "stablecoin_supply": float(val),
            }
        )
    if not rows:
        return pd.Series(name="stablecoin_supply", dtype="float64")
    df = pd.DataFrame(rows).drop_duplicates("time").set_index("time").sort_index()
    return df["stablecoin_supply"]


def fetch_stablecoin_supply(
    symbol: str | None = None,
    days: int = 365,
) -> pd.DataFrame:
    """Fetch aggregate stablecoin circulating supply (USD) from DefiLlama.

    Drop-in replacement for ``coingecko_data.fetch_stablecoin_supply`` with the
    same return contract, but backed by DefiLlama's full multi-year history.

    The ``symbol`` arg is accepted for SOURCE_REGISTRY signature symmetry but
    ignored — stablecoin supply is a market-wide series, not symbol-specific.

    Args:
        symbol: Ignored (kept for fetcher signature compatibility).
        days:   Lookback in days. Unlike CoinGecko, DefiLlama is not capped at
                365; the full requested window is returned when available.

    Returns:
        DataFrame indexed by UTC daily timestamp, columns:
          - stablecoin_supply: aggregate USD-pegged circulating supply (float).
        Empty DataFrame with the same column on fetch failure / no data.
    """
    try:
        full = _fetch_chart_cached()
    except requests.RequestException as exc:
        print(f"[defillama] stablecoin chart fetch failed ({exc})")
        return pd.DataFrame(columns=["stablecoin_supply"])

    if full.empty:
        return pd.DataFrame(columns=["stablecoin_supply"])

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    sliced = full[full.index >= cutoff]
    if sliced.empty:
        # Requested window predates available data — return what we have.
        sliced = full
    return sliced.rename("stablecoin_supply").to_frame()
