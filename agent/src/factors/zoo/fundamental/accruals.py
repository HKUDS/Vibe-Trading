"""Fundamental accruals quality factor (Sloan 1996)."""

from __future__ import annotations

import pandas as pd

from src.factors.base import zscore

__alpha_meta__ = {
    "id": "fund_accruals",
    "nickname": "Accruals - inverse (NI-CFO)/TA, Sloan 1996",
    "theme": ["quality"],
    "formula_latex": r"-\mathrm{zscore}_{x}\left(\frac{\mathrm{NI}-\mathrm{CFO}}{\mathrm{TA}}\right)",
    "columns_required": ["fund:accruals"],
    "universe": ["equity_us", "equity_cn", "equity_hk"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "Balance-sheet accrual proxy: high accruals indicate low earnings "
        "quality; sign inverted so high score = low accruals. PIT-safe from "
        "the fundamental panel; missing statements remain NaN and are "
        "excluded from that date's cross-section."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return cross-sectional z-scored inverse accruals."""
    return -zscore(panel["fund:accruals"])
