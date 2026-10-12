"""Fundamental cash-to-assets balance-sheet strength factor."""

from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div
from src.factors.base import zscore

__alpha_meta__ = {
    "id": "fund_cash_to_assets",
    "nickname": "Cash to assets - balance-sheet cash ratio",
    "theme": ["quality"],
    "formula_latex": r"\mathrm{zscore}_{x}\left(\frac{\mathrm{cash}}{\mathrm{total\_assets}}\right)",
    "columns_required": ["fund:cash", "fund:total_assets"],
    "universe": ["equity_us", "equity_cn", "equity_hk"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "Balance-sheet cash ratio (cash and equivalents / total assets): "
        "high cash holdings signal defensive capacity and financial "
        "flexibility. Zero or missing total assets become NaN via safe "
        "division before cross-sectional z-scoring; PIT-safe from the "
        "filed-date-anchored fundamental panel."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return cross-sectional z-scored cash-to-assets ratio."""
    cash_ratio = safe_div(panel["fund:cash"], panel["fund:total_assets"])
    return zscore(cash_ratio)
