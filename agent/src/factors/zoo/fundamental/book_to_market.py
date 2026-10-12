"""Fundamental book-to-market value factor (real Fama-French HML characteristic)."""

from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div
from src.factors.base import zscore

__alpha_meta__ = {
    "id": "fund_book_to_market",
    "nickname": "Book-to-market - equity over market cap (FF HML characteristic)",
    "theme": ["value"],
    "formula_latex": (
        r"\mathrm{zscore}_{x}\left("
        r"\frac{\mathrm{total\_equity}}{\mathrm{close}\times\mathrm{shares\_diluted}}"
        r"\right)"
    ),
    "columns_required": ["close", "fund:total_equity", "fund:shares_diluted"],
    "universe": ["equity_us", "equity_cn", "equity_hk"],
    "frequency": ["1d"],
    "decay_horizon": 252,
    "min_warmup_bars": 1,
    "notes": (
        "Valuation proxy: close times weighted-average diluted shares is not "
        "reported market capitalization; adjusted closes can change the level. "
        "Fama-French (1993) HML-style book-to-market proxy built from "
        "PIT-safe total equity and shares diluted aligned to the daily close "
        "panel; the academic_hml factor in the academic zoo is only a price "
        "proxy. High B/M (cheap relative to book value) scores high. "
        "market_cap = close x shares_diluted is computed here in the factor "
        "file by design: _fundamental_schema.py lines 210-212 deliberately "
        "keep price-dependent value factors such as book_to_market out of "
        "DERIVED_FIELDS because they need the aligned price panel. Zero or "
        "non-finite market cap becomes NaN via safe_div before cross-sectional "
        "z-scoring; missing statements remain NaN and are excluded from that "
        "date's cross-section."
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return cross-sectional z-scored book-to-market ratio."""
    market_cap = panel["close"] * panel["fund:shares_diluted"]
    book_to_market = safe_div(panel["fund:total_equity"], market_cap)
    return zscore(book_to_market)
