"""Industry-neutralized fundamental dividend-yield (TTM) value factor (CN daily market data)."""

from __future__ import annotations

import pandas as pd

from src.factors.base import zscore_by_group

__alpha_meta__ = {
    "id": "fund_dividend_yield_ind_neutral",
    "nickname": "Dividend yield TTM industry-neutral - within-industry dv_ttm (daily market data)",
    "theme": ["value"],
    "formula_latex": r"\mathrm{zscore}_{x\mid\mathrm{industry}}(\mathrm{DY_{TTM}})",
    "columns_required": ["val:dv_ttm"],
    "requires_sector": True,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "Industry-neutralized trailing dividend yield: each name is z-scored "
        "against its Shenwan level-1 industry peers instead of the whole "
        "cross-section (sector tag from tushare index_member_all SW2021 "
        "membership, point-in-time via in_date/out_date). This removes the "
        "industry confounding that dominates raw A-share dividend yield — "
        "mature banks and utilities pay structurally high dividends while "
        "growth industries pay almost none, so a raw high-yield screen is "
        "largely an industry bet. High dividend yield relative to industry "
        "peers scores high; dv_ttm is reported in percent units and "
        "cross-sectional z-scoring is scale-invariant, so no unit "
        "conversion is applied. A name with no industry label on a date "
        "stays NaN and is excluded from that date's cross-section; an "
        "industry group with fewer than two labelled names cannot form a "
        "within-group z-score and stays NaN. Keyed by trade_date, so "
        "PIT-safe by construction with no filing lag. Membership is "
        "point-in-time but the SW2021 taxonomy itself is retroactive — a "
        "name reclassified in 2021 carries its 2021 industry back through "
        "history. Lineage: "
        "industry-neutral variant of fund_dividend_yield (#1789 follow-up)."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return within-industry z-scored trailing dividend yield."""
    return zscore_by_group(panel["val:dv_ttm"], panel["sector"])
