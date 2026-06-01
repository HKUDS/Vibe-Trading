"""GTJA Alpha 128 (国泰君安 191 短周期交易型 alpha 因子, 2014).

Formula (verbatim from the report):
    100-100/(1+SUM(((H+L+C)/3*V) if up else 0,14)/SUM((... if down else 0),14))

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

ALPHA_ID = "gtja191_128"

__alpha_meta__ = {
    'id': 'gtja191_128',
    'theme': ['momentum'],
    'formula_latex': 'see body',
    'columns_required': ['open', 'high', 'low', 'close', 'volume'],
    'extras_required': [],
    'universe': ['equity_cn'],
    'frequency': ['1d'],
    'decay_horizon': 14,
    'min_warmup_bars': 16,
    'notes': '',
}


def compute(panel):
    """Compute gtja191_128.

    Args:
        panel: dict[str, pd.DataFrame] with at least the required columns.

    Returns:
        pd.DataFrame with index = panel["close"].index, columns = panel["close"].columns.
    """
    c = panel["close"]
    h = panel["high"]
    l = panel["low"]
    v = panel["volume"]
    tp = (h + l + c) / 3.0
    dtp = tp - tp.shift(1)
    up = (tp * v).where(dtp > 0, 0.0).rolling(14).sum()
    down = (tp * v).where(dtp < 0, 0.0).rolling(14).sum()
    ratio = safe_div(up, down)
    out = 100.0 - 100.0 / (1.0 + ratio)
    return out
