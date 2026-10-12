"""Fundamental cash-flow yield quality factor (CFO / total assets)."""

from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div
from src.factors.base import zscore

__alpha_meta__ = {
    "id": "fund_cfo_yield",
    "nickname": "CFO yield - operating cash flow over total assets",
    "theme": ["quality"],
    "formula_latex": r"\mathrm{zscore}_{x}\left(\frac{\mathrm{CFO}}{\mathrm{total\_assets}}\right)",
    "columns_required": ["fund:cfo", "fund:total_assets"],
    "universe": ["equity_us", "equity_cn", "equity_hk"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "Valuation proxy: close times weighted-average diluted shares is not "
        "reported market capitalization; adjusted closes can change the level. "
        "Cash-flow return on assets: the cash-backed counterpart of ROA, so "
        "accrual-heavy earnings score lower here. Zero or missing total "
        "assets become NaN via safe division before cross-sectional "
        "z-scoring; PIT-safe from the filed-date-anchored fundamental panel."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return cross-sectional z-scored CFO-to-assets yield."""
    cfo_yield = safe_div(panel["fund:cfo"], panel["fund:total_assets"])
    return zscore(cfo_yield)
