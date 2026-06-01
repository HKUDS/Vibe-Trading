"""GTJA Alpha #22.

Formula: SMA(((CLOSE-MEAN(CLOSE,6))/MEAN(CLOSE,6) - DELAY((CLOSE-MEAN(CLOSE,6))/MEAN(CLOSE,6),3)),12,1)
Source: 国泰君安 191 alpha 研报 (2014), alpha 22."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import (
    decay_linear,
    delta,
    rank,
    safe_div,
    signed_power,
    ts_argmax,
    ts_argmin,
    ts_corr,
    ts_cov,
    ts_max,
    ts_mean,
    ts_min,
    ts_rank,
    ts_std,
)

__alpha_meta__ = {
    "id": "gtja191_022",
    "theme": ['reversal'],
    "formula_latex": 'SMA(((CLOSE-MEAN(CLOSE,6))/MEAN(CLOSE,6) - DELAY((CLOSE-MEAN(CLOSE,6))/MEAN(CLOSE,6),3)),12,1)',
    "columns_required": ['close'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 12,
    "min_warmup_bars": 10,
    "notes": 'SMA(12, m=1) of 3-day-difference in price-deviation-from-MA6.',
}

def compute(panel: dict) -> pd.DataFrame:
    c = panel["close"]
    ma6 = ts_mean(c, 6)
    z = safe_div(c - ma6, ma6)
    diff = z - z.shift(3)
    return diff.ewm(alpha=1.0 / 12.0, adjust=False).mean()
