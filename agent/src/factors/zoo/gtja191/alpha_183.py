"""GTJA Alpha 183 (国泰君安 191 短周期交易型 alpha 因子, 2014).

Formula (verbatim from the report):
    MAX(SUMAC(CLOSE-MEAN(CLOSE,24))) - MIN(SUMAC(CLOSE-MEAN(CLOSE,24))) / STD(CLOSE,24)

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

ALPHA_ID = "gtja191_183"

__alpha_meta__ = {
    'id': 'gtja191_183',
    'theme': ['volatility'],
    'formula_latex': 'see body',
    'columns_required': ['close'],
    'extras_required': [],
    'universe': ['equity_cn'],
    'frequency': ['1d'],
    'decay_horizon': 24,
    'min_warmup_bars': 70,
    'notes': '',
}


def compute(panel):
    """Compute gtja191_183.

    Args:
        panel: dict[str, pd.DataFrame] with at least the required columns.

    Returns:
        pd.DataFrame with index = panel["close"].index, columns = panel["close"].columns.
    """
    c = panel["close"]
    dev = c - ts_mean(c, 24)
    csum = dev.rolling(24).sum()
    out = safe_div(ts_max(csum, 24) - ts_min(csum, 24), ts_std(c, 24))
    return out
