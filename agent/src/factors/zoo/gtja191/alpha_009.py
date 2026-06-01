"""GTJA Alpha #9.

Formula: SMA(((HIGH+LOW)/2-(DELAY(HIGH,1)+DELAY(LOW,1))/2)*(HIGH-LOW)/VOLUME,7,2)
Source: 国泰君安 191 alpha 研报 (2014), alpha 9."""

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
    "id": "gtja191_009",
    "theme": ['volume', 'microstructure'],
    "formula_latex": 'SMA(((HIGH+LOW)/2-(DELAY(HIGH,1)+DELAY(LOW,1))/2)*(HIGH-LOW)/VOLUME,7,2)',
    "columns_required": ['high', 'low', 'volume'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 7,
    "min_warmup_bars": 8,
    "notes": 'SMA(n=7, m=2) of midpoint change times range / volume.',
}

def compute(panel: dict) -> pd.DataFrame:
    h = panel["high"]
    l = panel["low"]
    v = panel["volume"]
    mid = (h + l) / 2.0
    pmid = (h.shift(1) + l.shift(1)) / 2.0
    x = (mid - pmid) * safe_div(h - l, v)
    return x.ewm(alpha=2.0 / 7.0, adjust=False).mean()
