"""Fundamental ROA quality factor."""

from __future__ import annotations

import pandas as pd

from src.factors.base import zscore

__alpha_meta__ = {
    "id": "fund_roa",
    "nickname": "ROA - return on assets (PIT-safe fundamentals)",
    "theme": ["quality"],
    "formula_latex": r"\mathrm{zscore}_{x}\left(\frac{\mathrm{net\_income}}{\mathrm{total\_assets}}\right)",
    "columns_required": ["fund:roa"],
    "universe": ["equity_us", "equity_cn", "equity_hk"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "PIT-safe return on assets (net income / total assets) from the "
        "fundamental panel; cross-sectional z-score per date. Higher ROA means "
        "a more profitable asset base and scores higher. Missing statements "
        "remain NaN and are excluded from that date's cross-section."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return cross-sectional z-scored ROA."""
    return zscore(panel["fund:roa"])
