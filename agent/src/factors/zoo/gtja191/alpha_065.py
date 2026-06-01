"""GTJA Alpha #65.

Formula: MEAN(CLOSE,6)/CLOSE
Source: 国泰君安 191 alpha 研报 (2014), alpha 65."""

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
    "id": "gtja191_065",
    "theme": ['reversal'],
    "formula_latex": 'MEAN(CLOSE,6)/CLOSE',
    "columns_required": ['close'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 6,
    "min_warmup_bars": 7,
    "notes": 'MA6 over close.',
}

def compute(panel: dict) -> pd.DataFrame:
    c = panel["close"]
    return safe_div(ts_mean(c, 6), c)
