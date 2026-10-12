"""Fundamental revenue-growth factor (YoY top-line growth)."""

from __future__ import annotations

import pandas as pd

from src.factors.base import zscore

__alpha_meta__ = {
    "id": "fund_revenue_growth",
    "nickname": "Revenue growth - YoY top-line expansion",
    "theme": ["growth"],
    "formula_latex": (
        r"\mathrm{zscore}_{x}\left("
        r"\frac{\mathrm{revenue}}{\mathrm{lag}_{365d}(\mathrm{revenue})}-1"
        r"\right)"
    ),
    "columns_required": ["fund:revenue_growth"],
    "universe": ["equity_us", "equity_cn", "equity_hk"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "PIT-safe revenue growth from the fundamental panel's derived field "
        "``revenue_growth`` (revenue / lag_365d(revenue) - 1, calendar-day "
        "lag per the #1564 lesson rather than a row-wise shift). High "
        "top-line growth scores high, matching the JoinQuant "
        "operating_revenue_growth_rate convention. Missing statements or a "
        "missing year-ago base remain NaN and are excluded from that date's "
        "cross-section."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return cross-sectional z-scored revenue growth."""
    return zscore(panel["fund:revenue_growth"])
