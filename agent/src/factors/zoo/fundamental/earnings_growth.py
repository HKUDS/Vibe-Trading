"""Fundamental earnings-growth factor (sign-safe YoY net-income growth)."""

from __future__ import annotations

import pandas as pd

from src.factors.base import zscore

__alpha_meta__ = {
    "id": "fund_earnings_growth",
    "nickname": "Earnings growth - sign-safe YoY net income expansion",
    "theme": ["growth"],
    "formula_latex": (
        r"\mathrm{zscore}_{x}\left("
        r"\frac{\Delta\,\mathrm{net\_income}}"
        r"{\left|\mathrm{lag}_{365d}(\mathrm{net\_income})\right|}"
        r"\right)"
    ),
    "columns_required": ["fund:earnings_growth"],
    "universe": ["equity_us", "equity_cn", "equity_hk"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "PIT-safe earnings growth from the fundamental panel's derived field "
        "``earnings_growth``. The schema-side formula is sign-safe: "
        "delta net_income / abs(lag_365d net_income), so a negative year-ago "
        "base does not flip the growth sign (the proposal #6 footnote "
        "resolution; the alternative NaN-on-negative-base was not chosen). "
        "Calendar-day lag per the #1564 lesson. High earnings growth scores "
        "high, matching the JoinQuant net_profit_growth_rate convention. "
        "Missing statements or a zero/missing year-ago base remain NaN and "
        "are excluded from that date's cross-section."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return cross-sectional z-scored earnings growth."""
    return zscore(panel["fund:earnings_growth"])
