"""GTJA Alpha #20.

Formula: ((CLOSE-DELAY(CLOSE,6))/DELAY(CLOSE,6))*100
Source: 国泰君安 191 alpha 研报 (2014), alpha 20."""

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
    "id": "gtja191_020",
    "theme": ['momentum'],
    "formula_latex": '((CLOSE-DELAY(CLOSE,6))/DELAY(CLOSE,6))*100',
    "columns_required": ['close'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 6,
    "min_warmup_bars": 7,
    "notes": '6d return in pct.',
}

def compute(panel: dict) -> pd.DataFrame:
    c = panel["close"]
    pc = c.shift(6)
    return safe_div(c - pc, pc) * 100.0
