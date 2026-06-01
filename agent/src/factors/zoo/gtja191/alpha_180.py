"""GTJA Alpha 180 (国泰君安 191 短周期交易型 alpha 因子, 2014).

Formula (verbatim from the report):
    ((MEAN(VOLUME,20) < VOLUME) ? ((-1*TSRANK(ABS(DELTA(CLOSE,7)),60)) * SIGN(DELTA(CLOSE,7))) : (-1*VOLUME))

Notes: 
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import (
    decay_linear,
    delta,
    rank,
    safe_div,
    scale,
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

ALPHA_ID = "gtja191_180"

__alpha_meta__ = {
    'id': 'gtja191_180',
    'theme': ['volume', 'reversal'],
    'formula_latex': 'see body',
    'columns_required': ['close', 'volume'],
    'extras_required': [],
    'universe': ['equity_cn'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 67,
    'notes': '',
}


def compute(panel):
    """Compute gtja191_180.

    Args:
        panel: dict[str, pd.DataFrame] with at least the required columns.

    Returns:
        pd.DataFrame with index = panel["close"].index, columns = panel["close"].columns.
    """
    c = panel["close"]
    v = panel["volume"]
    big = (ts_mean(v, 20) < v).astype("float64")
    left = -1.0 * ts_rank(delta(c, 7).abs(), 60) * np.sign(delta(c, 7))
    right = -1.0 * v
    out = left * big + right * (1.0 - big)
    return out
