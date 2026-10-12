"""Fundamental dividend-yield (TTM) value factor (CN daily market data)."""

from __future__ import annotations

import pandas as pd

from src.factors.base import zscore

__alpha_meta__ = {
    "id": "fund_dividend_yield",
    "nickname": "Dividend yield TTM - dv_ttm (daily market data)",
    "theme": ["value"],
    "formula_latex": r"\mathrm{zscore}_{x}(\mathrm{DY_{TTM}})",
    "columns_required": ["val:dv_ttm"],
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "Trailing dividend yield from the val: namespace (tushare "
        "daily_basic dv_ttm, CN A-share only), reported in percent units — "
        "cross-sectional z-scoring is scale-invariant, so no unit "
        "conversion is applied. High dividend yield scores high. Keyed by "
        "trade_date, so PIT-safe by construction with no filing lag. "
        "Missing dates or non-CN symbols stay NaN and are excluded from "
        "that date's cross-section. Lineage: JoinQuant style-pro divyild; "
        "akshare/Eastmoney dv_ttm convention."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return cross-sectional z-scored trailing dividend yield."""
    return zscore(panel["val:dv_ttm"])
