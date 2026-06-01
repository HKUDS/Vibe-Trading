"""GTJA Alpha #100.

Formula: STD(VOLUME,20)
Source: 国泰君安 191 alpha 研报 (2014), alpha 100."""

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
    "id": "gtja191_100",
    "theme": ['volatility', 'volume'],
    "formula_latex": 'STD(VOLUME,20)',
    "columns_required": ['volume'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 21,
    "notes": '20d std of volume.',
}

def compute(panel: dict) -> pd.DataFrame:
    return ts_std(panel["volume"], 20)
