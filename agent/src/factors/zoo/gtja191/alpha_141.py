"""GTJA Alpha 141 (国泰君安 191 短周期交易型 alpha 因子, 2014).

Formula (verbatim from the report):
    (RANK(CORR(RANK(HIGH),RANK(MEAN(VOLUME,15)),9))*-1)

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

ALPHA_ID = "gtja191_141"

__alpha_meta__ = {
    'id': 'gtja191_141',
    'theme': ['volume'],
    'formula_latex': 'rank(corr(rank(high),rank(mean(v,15)),9))*-1',
    'columns_required': ['high', 'volume', 'close'],
    'extras_required': [],
    'universe': ['equity_cn'],
    'frequency': ['1d'],
    'decay_horizon': 15,
    'min_warmup_bars': 24,
    'notes': '',
}


def compute(panel):
    """Compute gtja191_141.

    Args:
        panel: dict[str, pd.DataFrame] with at least the required columns.

    Returns:
        pd.DataFrame with index = panel["close"].index, columns = panel["close"].columns.
    """
    h = panel["high"]
    v = panel["volume"]
    out = rank(ts_corr(rank(h), rank(ts_mean(v, 15)), 9)) * -1.0
    return out
