"""Fundamental leverage factor (low leverage scores high)."""

from __future__ import annotations

import pandas as pd

from src.factors.base import zscore

__alpha_meta__ = {
    "id": "fund_leverage",
    "nickname": "Leverage - inverse debt/equity (low leverage scores high)",
    "theme": ["leverage"],
    "formula_latex": r"-\mathrm{zscore}_{x}\left(\frac{\mathrm{total\_debt}}{\mathrm{total\_equity}}\right)",
    "columns_required": ["fund:leverage"],
    "universe": ["equity_us", "equity_cn", "equity_hk"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "PIT-safe market leverage (total debt / total equity) from the "
        "fundamental panel; sign inverted so low leverage scores high — "
        "heavily levered firms carry distress risk and lower expected "
        "returns. Zero-equity or missing statements already yield NaN in the "
        "derived field and are excluded from that date's cross-section."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return negative cross-sectional z-scored leverage."""
    return -zscore(panel["fund:leverage"])
