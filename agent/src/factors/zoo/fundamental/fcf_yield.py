"""Fundamental free-cash-flow yield value factor (Lakonishok et al. 1994)."""

from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div
from src.factors.base import zscore

__alpha_meta__ = {
    "id": "fund_fcf_yield",
    "nickname": "FCF yield - (CFO - capex) over market cap",
    "theme": ["value"],
    "formula_latex": (
        r"\mathrm{zscore}_{x}\left("
        r"\frac{\mathrm{CFO}-\mathrm{capex}}"
        r"{\mathrm{close}\times\mathrm{shares\_diluted}}"
        r"\right)"
    ),
    "columns_required": ["close", "fund:cfo", "fund:capex", "fund:shares_diluted"],
    "universe": ["equity_us", "equity_cn", "equity_hk"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "Valuation proxy: close times weighted-average diluted shares is not "
        "reported market capitalization; adjusted closes can change the level. "
        "PIT-safe free-cash-flow yield: FCF = CFO - capex, scaled by market "
        "cap (close x shares_diluted) computed in the factor file per the "
        "_fundamental_schema.py price-dependent convention. Sign assumption: "
        "capex is reported as a positive magnitude (SEC concept "
        "PaymentsToAcquirePropertyPlantAndEquipment), so subtracting it from "
        "CFO yields FCF directly. High FCF yield (cheap on cash generation, "
        "cf. Lakonishok-Shleifer-Vishny 1994 cash-flow yield value factors) "
        "scores high. Zero/non-finite market cap becomes NaN via safe_div "
        "before cross-sectional z-scoring; missing statements remain NaN and "
        "are excluded from that date's cross-section."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return cross-sectional z-scored free-cash-flow yield."""
    fcf = panel["fund:cfo"] - panel["fund:capex"]
    market_cap = panel["close"] * panel["fund:shares_diluted"]
    return zscore(safe_div(fcf, market_cap))
