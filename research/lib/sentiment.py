"""
Sentiment / off-chain factor fetchers.

Sources:
- alternative.me Crypto Fear & Greed Index (free, daily, no auth)
"""

from datetime import datetime, timezone

import pandas as pd
import requests


def fetch_fear_greed(days: int = 365) -> pd.DataFrame:
    """Fetch Crypto Fear & Greed Index history from alternative.me.

    Args:
        days: lookback (the API supports any limit, daily granularity)

    Returns:
        DataFrame indexed by UTC date (00:00), columns: fng (0-100 int), classification (str)
    """
    r = requests.get(
        "https://api.alternative.me/fng/",
        params={"limit": days, "format": "json"},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json().get("data", [])
    rows: list[dict] = []
    for d in data:
        rows.append(
            {
                "time": datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc),
                "fng": int(d["value"]),
                "classification": d.get("value_classification", ""),
            }
        )
    df = pd.DataFrame(rows).drop_duplicates("time").set_index("time").sort_index()
    return df
