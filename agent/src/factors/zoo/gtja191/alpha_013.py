"""GTJA Alpha #13.

Formula: (((HIGH*LOW)^0.5) - VWAP)
Source: 国泰君安 191 alpha 研报 (2014), alpha 13."""

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
    "id": "gtja191_013",
    "theme": ['microstructure'],
    "formula_latex": '(((HIGH*LOW)^0.5) - VWAP)',
    "columns_required": ['high', 'low', 'volume', 'amount'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 1,
    "notes": 'Geometric mean of high/low minus vwap.',
}

def compute(panel: dict) -> pd.DataFrame:
    h = panel["high"]
    l = panel["low"]
    v = panel["volume"]
    vw = safe_div(panel["amount"], v * 100.0 + 1.0)
    geo = signed_power(h * l, 0.5)
    return geo - vw
