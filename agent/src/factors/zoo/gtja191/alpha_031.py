"""GTJA Alpha #31.

Formula: (CLOSE-MEAN(CLOSE,12))/MEAN(CLOSE,12)*100
Source: 国泰君安 191 alpha 研报 (2014), alpha 31."""

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
    "id": "gtja191_031",
    "theme": ['reversal'],
    "formula_latex": '(CLOSE-MEAN(CLOSE,12))/MEAN(CLOSE,12)*100',
    "columns_required": ['close'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 12,
    "min_warmup_bars": 13,
    "notes": 'Bias-12: deviation of close from MA12 in pct.',
}

def compute(panel: dict) -> pd.DataFrame:
    c = panel["close"]
    m12 = ts_mean(c, 12)
    return safe_div(c - m12, m12) * 100.0
