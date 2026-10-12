"""Fundamental price-to-book value factor (CN daily market data)."""

from __future__ import annotations

import pandas as pd

from src.factors.base import zscore

__alpha_meta__ = {
    "id": "fund_pb",
    "nickname": "P/B - inverse price-to-book (daily market data)",
    "theme": ["value"],
    "formula_latex": r"-\mathrm{zscore}_{x}(\mathrm{PB})",
    "columns_required": ["val:pb"],
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "Nonpositive multiples are excluded rather than ranked as cheap. "
        "Inverse price-to-book from the val: namespace (tushare daily_basic "
        "pb, CN A-share only): low PB (cheap relative to book value) scores "
        "high, the daily-market-data counterpart of fund_book_to_market. "
        "Keyed by trade_date, so PIT-safe by construction with no filing "
        "lag. Missing dates or non-CN symbols stay NaN and are excluded "
        "from that date's cross-section. Lineage: JoinQuant style "
        "book_to_price_ratio; akshare/Eastmoney pb convention."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return cross-sectional z-scored inverse price-to-book."""
    values = panel["val:pb"]
    return -zscore(values.where(values > 0))
