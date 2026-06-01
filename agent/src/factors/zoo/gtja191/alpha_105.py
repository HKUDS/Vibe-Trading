"""GTJA Alpha 105 (国泰君安 191 短周期交易型 alpha 因子, 2014).

Formula (verbatim from the report):
    (-1 * CORR(RANK(OPEN), RANK(VOLUME), 10))

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

ALPHA_ID = "gtja191_105"

__alpha_meta__ = {
    'id': 'gtja191_105',
    'theme': ['volume'],
    'formula_latex': '-1*corr(rank(open),rank(volume),10)',
    'columns_required': ['open', 'volume', 'close'],
    'extras_required': [],
    'universe': ['equity_cn'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 10,
    'notes': '',
}


def compute(panel):
    """Compute gtja191_105.

    Args:
        panel: dict[str, pd.DataFrame] with at least the required columns.

    Returns:
        pd.DataFrame with index = panel["close"].index, columns = panel["close"].columns.
    """
    o = panel["open"]
    v = panel["volume"]
    out = -1.0 * ts_corr(rank(o), rank(v), 10)
    return out
