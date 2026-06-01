"""GTJA Alpha #96.

Formula: SMA(SMA((CLOSE-TSMIN(LOW,9))/(TSMAX(HIGH,9)-TSMIN(LOW,9))*100,3,1),3,1)
Source: 国泰君安 191 alpha 研报 (2014), alpha 96."""

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
    "id": "gtja191_096",
    "theme": ['momentum'],
    "formula_latex": 'SMA(SMA((CLOSE-TSMIN(LOW,9))/(TSMAX(HIGH,9)-TSMIN(LOW,9))*100,3,1),3,1)',
    "columns_required": ['close', 'high', 'low'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 9,
    "min_warmup_bars": 12,
    "notes": 'KDJ %D-style double smoothed.',
}

def compute(panel: dict) -> pd.DataFrame:
    c = panel["close"]
    h = panel["high"]
    l = panel["low"]
    raw = safe_div(c - ts_min(l, 9), ts_max(h, 9) - ts_min(l, 9)) * 100.0
    return raw.ewm(alpha=1.0 / 3.0, adjust=False).mean().ewm(alpha=1.0 / 3.0, adjust=False).mean()
