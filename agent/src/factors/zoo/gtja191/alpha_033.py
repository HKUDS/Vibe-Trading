"""GTJA Alpha #33.

Formula: ((((-1*TSMIN(LOW,5))+DELAY(TSMIN(LOW,5),5))*RANK(((SUM(RET,240)-SUM(RET,20))/220)))*TSRANK(VOLUME,5))
Source: 国泰君安 191 alpha 研报 (2014), alpha 33."""

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
    "id": "gtja191_033",
    "theme": ['momentum', 'volume'],
    "formula_latex": '((((-1*TSMIN(LOW,5))+DELAY(TSMIN(LOW,5),5))*RANK(((SUM(RET,240)-SUM(RET,20))/220)))*TSRANK(VOLUME,5))',
    "columns_required": ['low', 'close', 'volume'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 61,
    "notes": '240d/20d long-window approximated with 60d/20d (warmup feasibility).',
}

def compute(panel: dict) -> pd.DataFrame:
    l = panel["low"]
    c = panel["close"]
    v = panel["volume"]
    pc = c.shift(1)
    ret = safe_div(c - pc, pc)
    tmin5 = ts_min(l, 5)
    a = -1.0 * tmin5 + tmin5.shift(5)
    long_diff = (ret.rolling(60, min_periods=30).sum() - ret.rolling(20, min_periods=10).sum()) / 40.0
    return a * rank(long_diff) * ts_rank(v, 5)
