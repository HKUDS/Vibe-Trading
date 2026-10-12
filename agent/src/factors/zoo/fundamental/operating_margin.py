"""Fundamental operating-margin quality factor."""

from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div
from src.factors.base import zscore

__alpha_meta__ = {
    "id": "fund_operating_margin",
    "nickname": "Operating margin - operating income over revenue",
    "theme": ["quality"],
    "formula_latex": r"\mathrm{zscore}_{x}\left(\frac{\mathrm{operating\_income}}{\mathrm{revenue}}\right)",
    "columns_required": ["fund:operating_income", "fund:revenue"],
    "universe": ["equity_us", "equity_cn", "equity_hk"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "Operating profitability (operating income / revenue), "
        "cross-sectionally z-scored per date. Captures pricing power and cost "
        "efficiency before financing and tax effects. Zero-revenue or missing "
        "statements become NaN via safe division and are excluded from that "
        "date's cross-section; PIT-safe from the fundamental panel."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return cross-sectional z-scored operating margin."""
    margin = safe_div(panel["fund:operating_income"], panel["fund:revenue"])
    return zscore(margin)
