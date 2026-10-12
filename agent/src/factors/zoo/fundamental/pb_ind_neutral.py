"""Industry-neutralized fundamental price-to-book value factor (CN daily market data)."""

from __future__ import annotations

import pandas as pd

from src.factors.base import zscore_by_group

__alpha_meta__ = {
    "id": "fund_pb_ind_neutral",
    "nickname": "P/B industry-neutral - inverse within-industry price-to-book (daily market data)",
    "theme": ["value"],
    "formula_latex": r"-\mathrm{zscore}_{x\mid\mathrm{industry}}(\mathrm{PB})",
    "columns_required": ["val:pb"],
    "requires_sector": True,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "Nonpositive multiples are excluded rather than ranked as cheap. "
        "Industry-neutralized inverse price-to-book: each name is z-scored "
        "against its Shenwan level-1 industry peers instead of the whole "
        "cross-section (sector tag from tushare index_member_all SW2021 "
        "membership, point-in-time via in_date/out_date). This removes the "
        "industry confounding that dominates raw A-share PB — banks and "
        "cyclicals are structurally cheap on book value while technology "
        "names are structurally expensive, so a raw low-PB screen is largely "
        "an industry bet. Low PB relative to industry peers scores high. A "
        "name with no industry label on a date stays NaN and is excluded "
        "from that date's cross-section; an industry group with fewer than "
        "two labelled names cannot form a within-group z-score and stays "
        "NaN. Keyed by trade_date, so PIT-safe by construction with no "
        "filing lag. Membership is point-in-time but the SW2021 taxonomy "
        "itself is retroactive — a name reclassified in 2021 carries its "
        "2021 industry back through history. Lineage: industry-neutral "
        "variant of fund_pb (#1789 "
        "follow-up)."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return within-industry z-scored inverse price-to-book."""
    values = panel["val:pb"]
    return -zscore_by_group(values.where(values > 0), panel["sector"])
