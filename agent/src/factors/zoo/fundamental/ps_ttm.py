"""Fundamental price-to-sales (TTM) value factor (CN daily market data)."""

from __future__ import annotations

import pandas as pd

from src.factors.base import zscore

__alpha_meta__ = {
    "id": "fund_ps_ttm",
    "nickname": "P/S TTM - inverse price-to-sales (daily market data)",
    "theme": ["value"],
    "formula_latex": r"-\mathrm{zscore}_{x}(\mathrm{PS_{TTM}})",
    "columns_required": ["val:ps_ttm"],
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "Nonpositive multiples are excluded rather than ranked as cheap. "
        "Inverse trailing price-to-sales from the val: namespace (tushare "
        "daily_basic ps_ttm, CN A-share only): low PS scores high. PS stays "
        "informative for loss-making names where earnings yield fails. "
        "Keyed by trade_date, so PIT-safe by construction with no filing "
        "lag. Missing dates or non-CN symbols stay NaN and are excluded "
        "from that date's cross-section. Lineage: JoinQuant style-pro "
        "sales-to-price; akshare/Eastmoney ps_ttm convention."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return cross-sectional z-scored inverse price-to-sales (TTM)."""
    values = panel["val:ps_ttm"]
    return -zscore(values.where(values > 0))
